import streamlit as st
from streamlit_extras.switch_page_button import switch_page
from datetime import datetime, timedelta
import plotly.express as px
import pandas as pd
import folium
from streamlit_folium import st_folium
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import PromptTemplate
from dotenv import load_dotenv
import os
from data import * 
import requests
import time
from PIL import Image, ImageDraw
import random
import threading
from streamlit.runtime.scriptrunner import add_script_run_ctx
import redis 
import pickle

st.set_page_config(layout="wide", page_title='SolarGis', page_icon = 'solargislogo.png')
load_dotenv()
gemapi_key = os.getenv('GEMINI_API_KEY')

headers = {
    "Content-Type": "application/json",
    "Token": os.getenv('DINO_TOKEN')
}

redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=False)
EXPIRATION_TIME = 1800  # 30 minutes

def set_redis_state(key, value):
    redis_client.setex(key, EXPIRATION_TIME, pickle.dumps(value))

def get_redis_state(key, default_value=None):
    value = redis_client.get(key)
    return pickle.loads(value) if value else default_value


if get_redis_state("descriptions") is None:
    set_redis_state("descriptions", [])
if get_redis_state("bbox_center") is None:
    set_redis_state("bbox_center", [79.0710765, 21.153512])
if get_redis_state("response_radiation") is None:
    st.warning("Your bounding box has changed. Kindly reselect.")
    set_redis_state("response_radiation", radiance_data)
if get_redis_state("response_pv_power") is None:
    set_redis_state("response_pv_power", pv_data)
if get_redis_state("dsb2") is None:
    set_redis_state("dsb2", True)
if get_redis_state("segmented_images") is None:
    set_redis_state("segmented_images", [])
if get_redis_state("upis") is None:
    set_redis_state("upis", [])

# Helper functions
def upload_to_imgbb(image_path, api_key=os.getenv('IMGDB_API_KEY')):
    url = f"https://api.imgbb.com/1/upload?expiration=3600&key={api_key}"
    with open(image_path, "rb") as img_file:
        response = requests.post(url, files={"image": img_file})
        if response.status_code == 200:
            data = response.json().get("data")
            return data.get("url")
        return None

def random_color():
    return "#{:06x}".format(random.randint(0, 0xFFFFFF))

def draw_boxes(image_path, results):
    image = Image.open(image_path)
    draw = ImageDraw.Draw(image)
    category_colors = {}
    category_counts = {}
    for result in results:
        bbox = result["bbox"]
        label = result["category"]
        if label not in category_colors:
            category_colors[label] = random_color()
            category_counts[label] = 1
        else: 
            category_counts[label] += 1
        color = category_colors[label]
        draw.rectangle(bbox, outline=color, width=2)
        draw.text((bbox[0], bbox[1]), label, fill=color)
    description = '<br>'.join([f'{cat}: {count}' for cat, count in category_counts.items()])
    descriptions = get_redis_state("descriptions")
    descriptions.append(description)
    set_redis_state("descriptions", descriptions)
    return image

def object_detect(image_url, image_save_path): 
    body = {
        "image": image_url,
        "prompts": [
            {"type": "text", "text": "building"},
            {"type": "text", "text": "trees"},
            {"type": "text", "text": "wall"},
            {"type": "text", "text": "pole"}
        ],
        "model": 'GroundingDino-1.5-Pro',
        "targets": ["bbox"]
    }

    resp = requests.post('https://api.deepdataspace.com/tasks/detection', json=body, headers=headers)

    if resp.status_code == 200:
        json_resp = resp.json()
        task_uuid = json_resp["data"]["task_uuid"]

        for _ in range(60):
            resp = requests.get(f'https://api.deepdataspace.com/task_statuses/{task_uuid}', headers=headers)
            if resp.status_code != 200:
                break
            json_resp = resp.json()
            if json_resp["data"]["status"] not in ["waiting", "running"]:
                break
            time.sleep(1)

        if json_resp["data"]["status"] == "success":
            results = json_resp["data"]["result"]["objects"]
            response = requests.get(image_url)
            with open(image_save_path, 'wb') as f:
                f.write(response.content)
            image_with_boxes = draw_boxes(image_save_path, results)
            image_with_boxes.save(image_save_path)
            url = upload_to_imgbb(image_save_path)
            segmented_images = get_redis_state("segmented_images", [])
            segmented_images.append(url)
            set_redis_state("segmented_images", segmented_images)


def process_image(uploaded_image, unique_id):
    file_path = f"temp_{unique_id}_{uploaded_image.name}"
    with open(file_path, "wb") as file:
        file.write(uploaded_image.getbuffer())
    img_url = upload_to_imgbb(file_path)
    object_detect(img_url, file_path)
    return file_path  

def threaded_process_images(uploaded_images):
    threads = []
    file_paths = []

    def thread_function(image, result_list, index):
        file_path = process_image(image, unique_id=index)
        result_list.append(file_path)

    for i, image in enumerate(uploaded_images):
        thread = threading.Thread(target=thread_function, args=(image, file_paths, i))
        add_script_run_ctx(thread)
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    for file_path in file_paths:
        if os.path.exists(file_path):
            os.remove(file_path)

with open("style2.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    temperature=0, 
    api_key=gemapi_key)

system_prompt = """
You are an expert in renewable energy which gives to the point brief answers. Given the following PV power estimates in KW recorded after every 30 minutes, describe in brief how many appliances can be run from the power estimates.(no need to be precise, give a general list of appliances in brief.). Your responses must not exceed 100 words.
"""    
prompt_template = PromptTemplate(
    input_variables=["pv_data"],
    template=system_prompt + "\n\n{pv_data}"
)

left_col,right_col = st.columns([1.9,2])

def infer(pv_data):
    res = llm.invoke(prompt_template.format(pv_data=pv_data))
    st.sidebar.text_area('AI generated Inference:',res.content, height=450)

go_back = st.sidebar.button("Re-select Bounding box", use_container_width=True)

if go_back: 
    switch_page('main')

st.sidebar.write("Your selected bounding box:")
bbox_center = get_redis_state("bbox_center")
m = folium.Map(location=[bbox_center[1], bbox_center[0]], zoom_start=14)
folium.Marker([bbox_center[1], bbox_center[0]], popup="Location").add_to(m)

with st.sidebar:
    st_folium(m, width=300, height=200)

with left_col:
    with st.form(key="calc"):
        st.markdown('<div class="container">Initial PV Output</div>', unsafe_allow_html=True)
        response_pv_power = get_redis_state("response_pv_power", pv_data)
        data = response_pv_power['estimated_actuals']
        times = [(datetime.strptime(entry["period_end"], "%Y-%m-%dT%H:%M:%S.%f0Z") + timedelta(hours=5, minutes=30)).strftime('%H:%M') for entry in data]
        pv_estimates = [entry["pv_estimate"] for entry in data]
        
        df = pd.DataFrame({'Time': times, 'PV Estimate': pv_estimates})
        df = df.sort_values('Time')
        
        fig = px.line(df, x='Time', y='PV Estimate', title='Estimated PV Power Output',
                    labels={'Time': 'Time (hours)', 'PV Estimate': 'PV Estimate (kW)'},
                    color_discrete_sequence=px.colors.sequential.Blues,
                    markers=True)
        
        fig.update_layout(
            yaxis=dict(range=[0, max(pv_estimates) + 1]),
            xaxis=dict(tickmode='linear', tick0=0, dtick=2, tickangle=-45),
            template='plotly_white',
            height=360
        )
        st.plotly_chart(fig)
        pv_data = df.to_json(orient='records')
        c1,c2 = st.columns([3,1])
        with c1:
            st.slider("Time range:", 1, 24, 24)
        with c2:
            st.markdown(" ")
            st.markdown(" ")
            st.form_submit_button("Re-calculate",use_container_width=True)
        infer(pv_data)

with right_col:
    with st.form(key="graph"):
        st.markdown('<div class="container">Solar Irradiance Data</div>', unsafe_allow_html=True)
        response_radiation = get_redis_state("response_radiation", radiance_data)
        data = response_radiation['estimated_actuals']

        times = [(datetime.strptime(entry["period_end"], "%Y-%m-%dT%H:%M:%S.%f0Z") + timedelta(hours=5, minutes=30)).strftime('%H:%M') for entry in data]
        ghi_values = [entry["ghi"] for entry in data]
        df = pd.DataFrame({'Time': times, 'GHI': ghi_values})
        df = df.sort_values('Time')
        fig = px.line(df, x='Time', y='GHI', title='Horizaontal Solar Irradiance',
                    labels={'Time': 'Time (hours)', 'GHI': 'GHI'},
                    color_discrete_sequence=px.colors.sequential.Reds,
                    markers=True)
        fig.update_layout(
            yaxis=dict(range=[0, max(ghi_values) + 10]),
            xaxis=dict(tickmode='linear', tick0=0, dtick=2,tickangle=-50),
            template='plotly_white',
            height=360
        )
        st.plotly_chart(fig)
        c1,c2 = st.columns([4,1])
        with c1:
            st.slider("Time range:", 1, 24, 24)
        with c2:
            st.markdown(" ")
            st.markdown(" ")
            st.form_submit_button("Redraw",use_container_width=True)

col1, col2 = st.columns([2,3])
with col1: 
    with st.form(key="img"):
        st.markdown('<div class="container">Image uploader</div>', unsafe_allow_html=True)
        uploaded_images = st.file_uploader("Upload images for segmentation:", accept_multiple_files=True,type=["jpg", "png", "jpeg"]) 
        st.write("Upload in sequence: ['North', 'West', 'South', 'East']")
        st.selectbox("Type of image:", ['LiDar(Iphone)', 'Stereo']) 
        upload_image = st.form_submit_button("Upload Images", use_container_width=True)
        if upload_image and len(uploaded_images)==4: 
            set_redis_state("dsb2", False)
        else: 
            set_redis_state("dsb2", True)

with col2: 
    with st.form(key = 'uploaded_images'): 
        st.markdown('<div class="container">Uploaded Images</div>', unsafe_allow_html=True)
        placeholder_image_url = "placeholder_image.png"
        cols = st.columns(2)
        placeholders = []
        labels = ['North', 'West', 'South', 'East']
        for i in range(4):
                with cols[i % 2]:
                    st.markdown(f"<div style='text-align: center;'>{labels[i]}</div>", unsafe_allow_html=True)
                    if upload_image and len(uploaded_images) == 4:
                        placeholders.append(st.image(uploaded_images[i], use_column_width=True))
                    else:
                        placeholders.append(st.image(placeholder_image_url, use_column_width=True))
        segment = st.form_submit_button("Segment", use_container_width=True, disabled=get_redis_state("dsb2"), help="Upload all images first.")
        if segment and len(uploaded_images) == 4: 
            with st.spinner("Restrain from re-freshing while we segment your images..."):
                    set_redis_state("upis", uploaded_images)
                    switch_page('North')

if not upload_image and len(uploaded_images) != 4:
    with col1:
        youtube_code = '''
        <div style="width:100%; height:auto; max-width:560px; overflow:hidden;">
        <iframe id="ytplayer" 
                src="https://www.youtube.com/embed/5XentgFYEfA?autoplay=1&mute=1&loop=1&playlist=5XentgFYEfA" 
                frameborder="0" 
                allow="autoplay; encrypted-media" 
                allowfullscreen
                style="width:100%; height:160px;">
        </iframe>
        </div>
        '''
        with st.form(key='height'):
            st.write(youtube_code, unsafe_allow_html=True)
            lcol, rcol = st.columns([2,1])
            with lcol: 
                st.slider('Reference height:', min_value=0, max_value=100, value=0, format='%.1f')
            with rcol: 
                st.form_submit_button('Change Reference height')