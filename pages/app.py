import streamlit as st
from streamlit_extras.switch_page_button import switch_page
from datetime import datetime
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
import requests
from PIL import Image, ImageDraw
import random

st.set_page_config(layout="wide")
load_dotenv()
gemapi_key = os.getenv('GEMINI_API_KEY')

headers = {
    "Content-Type": "application/json",
    "Token": os.getenv('DINO_TOKEN')
}

if 'descriptions' not in st.session_state: 
    st.session_state.descriptions = []
if 'bbox_center' not in st.session_state: 
    st.session_state.bbox_center = [79.0729, 21.1537]
if 'response_radiation' not in st.session_state: 
    st.warning("Your bounding box has changed. Kindly reselect.")
    st.session_state.response_radiation = radiance_data
if 'response_pv_power' not in st.session_state:
    st.session_state.response_pv_power = pv_data
if 'dsb2' not in st.session_state:
    st.session_state.dsb2 = True
if 'segmented_images' not in st.session_state:
    st.session_state.segmented_images = []
if 'upis' not in st.session_state: 
    st.session_state.upis = []

def upload_to_imgbb(image_path, api_key=os.getenv('IMGDB_API_KEY')):
    url = f"https://api.imgbb.com/1/upload?expiration=3600&key={api_key}"
    with open(image_path, "rb") as img_file:
        response = requests.post(url, files={"image": img_file})
        if response.status_code == 200:
            data = response.json().get("data")
            return data.get("url")
        else:
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
                    category_counts[label]+=1
                color = category_colors[label]
                draw.rectangle(bbox, outline=color, width=2)
                draw.text((bbox[0], bbox[1]), label, fill=color)
            s = ''
            for category, count in category_counts.items():
                s += f'{category} : {count}<br>'
            st.session_state.descriptions.append(s)
            os.remove(image_path)
            return image


def object_detect(image_url): 
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

        max_retries = 60
        retry_count = 0
        while retry_count < max_retries:
            resp = requests.get(f'https://api.deepdataspace.com/task_statuses/{task_uuid}', headers=headers)
            if resp.status_code != 200:
                break
            json_resp = resp.json()
            if json_resp["data"]["status"] not in ["waiting", "running"]:
                break
            time.sleep(1)
            retry_count += 1

        if json_resp["data"]["status"] == "failed":
            print(f'failed resp: {json_resp}')
        elif json_resp["data"]["status"] == "success":
            results = json_resp["data"]["result"]["objects"]
            image_url = body["image"]
            image_path = "local_image.jpg"
            response = requests.get(image_url)
            with open(image_path, 'wb') as f:
                f.write(response.content)
            
            image_with_boxes = draw_boxes(image_path, results)
            image_with_boxes.save('image_with_boxes.png')
            url = upload_to_imgbb('image_with_boxes.png')
            os.remove('image_with_boxes.png')
            st.session_state.segmented_images.append(url)

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

with open("style2.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

left_col,right_col = st.columns([1.9,2])

def infer(pv_data):
    res = llm.invoke(prompt_template.format(pv_data=pv_data))
    st.sidebar.text_area('AI generated Inference:',res.content, height=400)

go_back = st.sidebar.button("Re-select Bounding box", use_container_width=True)

if go_back: 
    switch_page('main')

st.sidebar.write("Your selected bounding box:")
m = folium.Map(location=[st.session_state.bbox_center[1], st.session_state.bbox_center[0]], zoom_start=14)
folium.Marker([st.session_state.bbox_center[1], st.session_state.bbox_center[0]], popup="Location").add_to(m)
with st.sidebar:
    st_folium(m, width=300, height=200)

with left_col:
    with st.form(key="calc"):
        st.markdown('<div class="container">Initial PV Output</div>', unsafe_allow_html=True)
        data = st.session_state.response_pv_power['estimated_actuals']
        times = [datetime.strptime(entry["period_end"], "%Y-%m-%dT%H:%M:%S.%f0Z").strftime('%H:%M') for entry in data]
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
        data = st.session_state.response_radiation['estimated_actuals']
        times = [datetime.strptime(entry["period_end"], "%Y-%m-%dT%H:%M:%S.%f0Z").strftime('%H:%M') for entry in data]
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
            st.session_state.dsb2 = False
        else: 
            st.session_state.dsb2 = True

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
        segment = st.form_submit_button("Segment", use_container_width=True, disabled=st.session_state.dsb2, help="Upload all images first.")
        if segment and len(uploaded_images) == 4: 
            with st.spinner("It may take us a while to segment, you will be automatically re-routed."):
                for uploaded_image in uploaded_images:
                    file_path = uploaded_image.name
                    with open(file_path, "wb") as file:
                        file.write(uploaded_image.getbuffer())
                    img_url=upload_to_imgbb(file_path)
                    object_detect(img_url)
                    os.remove(file_path)
       
            if len(st.session_state.segmented_images) == 4:
                print(st.session_state.segmented_images)
                st.session_state.upis = uploaded_images
                switch_page('North')

if upload_image and len(uploaded_images) == 4:
    with st.container(border=True):
        st.markdown(
                """
                <div style="text-align: center;">
                    <p style="color: white;">Segmentation Controls</p>
                    <hr style="border: 1px solid white; margin-top: 0;">
                </div>
                """,
                unsafe_allow_html=True
            )
        c1,c2,c3,c4 = st.columns(4)
        with c1: 
            height = st.slider("Adjust height:", 0, 100, 50)
        with c2:
            prediction_iou = st.slider('Prediction IOU threshold (default=0.8)', min_value=0.0, max_value=1.0, value=0.8)
        with c3:
            stability_score = st.slider('Stability score threshold (default=0.85)', min_value=0.0, max_value=1.0, value=0.85)
        with c4: 
            box_nms = st.slider('Box NMS threshold (default=0.7)', min_value=0.0, max_value=1.0, value=0.7)
else:
    with col1: 
        with st.container(border=True):
            st.markdown(
                """
                <div style="text-align: center;">
                    <p style="color: white;">Segmentation Controls</p>
                    <hr style="border: 1px solid white; margin-top: 0;">
                </div>
                """,
                unsafe_allow_html=True
            )
            
            column1, column2 = st.columns(2)
            with column1: 
                height = st.slider("Adjust height:", 0, 100, 50)
                prediction_iou = st.slider('Prediction IOU threshold (default=0.8)', min_value=0.0, max_value=1.0, value=0.8)
            with column2:
                stability_score = st.slider('Stability score threshold (default=0.85)', min_value=0.0, max_value=1.0, value=0.85)
                box_nms = st.slider('Box NMS threshold (default=0.7)', min_value=0.0, max_value=1.0, value=0.7)
