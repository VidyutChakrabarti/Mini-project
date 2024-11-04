import streamlit as st
from streamlit_extras.switch_page_button import switch_page
import time
from streamlit_folium import st_folium
import folium 
from data import *
from helperfuncs import combine_dataframes
import pandas as pd
import redis
import pickle

redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=False)
EXPIRATION_TIME = 1800  

def set_redis_state(key, value):
    redis_client.setex(key, EXPIRATION_TIME, pickle.dumps(value))

def get_redis_state(key, default_value=None):
    value = redis_client.get(key)
    return pickle.loads(value) if value else default_value

st.set_page_config(layout="wide", page_title='SolarGis', page_icon = 'solargislogo.png')
with open("est_style.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

if get_redis_state("bbox_center") is None:
    set_redis_state("bbox_center", [79.0729, 21.1537])

if get_redis_state("segmented_images") is None:
    set_redis_state("segmented_images", [])


directions = ['North', 'West','South','East']

segmented_images = get_redis_state("segmented_images", [])
descriptions = get_redis_state("descriptions", [])
if len(segmented_images) == 4:
    images = []
    for i, img in enumerate(segmented_images): 
        images.append({
            'path': img, 
            'title': directions[i], 
            'desc': f'<b>AUTO OBJECT DETECTION:</b><br><br>{descriptions[i]}'
        })


else: 
    images = [
        {'path': 'https://i.ibb.co/3rmjPhS/image-with-boxes.png', 'title': directions[0] , 'desc': f'<b>AUTO OBJECT DETECTION:</b><br><br>{desc[0]}'},
        {'path': 'https://i.ibb.co/chT5FWZ/image-with-boxes.png', 'title': directions[1], 'desc': f'<b>AUTO OBJECT DETECTION:</b><br><br>{desc[1]}'},
        {'path': 'https://i.ibb.co/DzqhQZH/image-with-boxes.png', 'title': directions[2], 'desc': f'<b>AUTO OBJECT DETECTION:</b><br><br>{desc[2]}'},
        {'path': 'https://i.ibb.co/YRqDmz3/image-with-boxes.png', 'title': directions[3], 'desc': f'<b>AUTO OBJECT DETECTION:</b><br><br>{desc[3]}'},      
    ]


st.sidebar.markdown('<h1 class="gradient-text">Partial Shading Re-estimation</h1>', unsafe_allow_html=True)

if st.sidebar.button("Go to Main Page", use_container_width=True):
    switch_page('main')
if st.sidebar.button("Resubmit Images", use_container_width=True):
    switch_page('app')
if st.sidebar.button("Reselect Obstacles", use_container_width=True):
    switch_page('North')


st.sidebar.write("Your selected bounding box:")
bbox_center = get_redis_state("bbox_center", [79.0729, 21.1537])  

# Create the Folium map using the bbox_center coordinates
m = folium.Map(location=[bbox_center[1], bbox_center[0]], zoom_start=14)
folium.Marker([bbox_center[1], bbox_center[0]], popup="Location").add_to(m)

with st.sidebar:
    st_folium(m, width=300, height=200)

def preload_cards(images):
    cards = []
    for index, imag in enumerate(images):
        card_html = f"""
        <div class="card card-{index}">
            <img src="{imag['path']}" class = 'img-container'>
            <p style="font-size: 1.6em; margin-bottom: 0px;">{imag['title']}</p>
            <hr style="border: 1px solid white; margin-top: 0px; margin-bottom: 4px;">
            <div style="border-left: 1px solid white;border-right: 1px solid white;border-bottom: 1px solid white; padding: 10px;">
                <p>{imag['desc']}</p>
            </div>   
        </div>
        """
        cards.append(card_html)
    return cards

if get_redis_state("cards") is None:
    set_redis_state("cards", preload_cards(images))

if get_redis_state("start_index") is None:
    set_redis_state("start_index", 0)

if get_redis_state("animation_class") is None:
    set_redis_state("animation_class", [""] * len(get_redis_state("cards")))

if get_redis_state("direction") is None:
    set_redis_state("direction", '')

if get_redis_state("combined_df") is None:
    set_redis_state("combined_df", None)
    
def update_animation_classes(direction):
    cards = get_redis_state("cards")
    start_index = get_redis_state("start_index")

    if direction == 'left':
        animation_class = ["card-slide-left"] * len(cards)
        animation_class[start_index] = 'card-slide-out-to-left'
        animation_class[(start_index + 3) % len(cards)] = 'card-slide-in-from-right'
    elif direction == 'right':
        animation_class = ["card-slide-right"] * len(cards)
        animation_class[(start_index + len(cards) - 1) % len(cards)] = 'card-slide-in-from-left'
        animation_class[(start_index + 2) % len(cards)] = 'card-slide-out-to-right'

    set_redis_state("animation_class", animation_class)


col1, col2= st.columns([1,1])
with col1:
    left = st.button('◀ Shift left', use_container_width=True)
    if left:
        update_animation_classes('left')
        set_redis_state('direction', 'left') 
with col2:
    right = st.button('Shift Right ▶', use_container_width=True)
    if right:
        update_animation_classes('right')
        
        start_index = get_redis_state('start_index', 0) 
        new_start_index = start_index % len(get_redis_state('cards', []))  
        set_redis_state('start_index', new_start_index) 
        
        set_redis_state('direction', 'right') 

direction = get_redis_state("direction")
start_index = get_redis_state("start_index")
cards = get_redis_state("cards")
animation_class = get_redis_state("animation_class")

if direction == 'left':
    cols = st.columns(3)
    placeholders = [col.empty() for col in cols]
    
    for i in range(3):
        card_index = (start_index + i) % len(cards)
        card_class = animation_class[card_index]
        placeholders[i].markdown(f'<div class="{card_class}">{cards[card_index]}</div>', unsafe_allow_html=True)
    
    time.sleep(0.5)
    
    start_index = (start_index + 1) % len(cards)
    
    for i in range(3):
        card_index = (start_index + i) % len(cards)
        card_class = animation_class[card_index]
        if card_class == "card-slide-left":
            card_class = ""
        placeholders[i].markdown(f'<div class="{card_class}">{cards[card_index]}</div>', unsafe_allow_html=True)
    set_redis_state("direction", '')
    set_redis_state("animation_class", [""] * len(cards))
    set_redis_state("start_index", start_index)
     
elif direction == 'right':
    cols = st.columns(3)
    placeholders = [col.empty() for col in cols]

    for i in range(3):
        card_index = (start_index + i) % len(cards)
        card_class = animation_class[card_index]
        placeholders[i].markdown(f'<div class="{card_class}">{cards[card_index]}</div>', unsafe_allow_html=True)
    
    time.sleep(0.5)
    start_index = (start_index - 1) % len(cards)
    
    for i in range(3):
        card_index = (start_index + i) % len(cards)
        card_class = animation_class[card_index]
        if card_class == "card-slide-right":
            card_class = ""
        placeholders[i].markdown(f'<div class="{card_class}">{cards[card_index]}</div>', unsafe_allow_html=True) 
    # Resetting direction and animation class
    set_redis_state("direction", '')
    set_redis_state("animation_class", [""] * len(cards))
    set_redis_state("start_index", start_index)
    


    
else:
    cols = st.columns(3)
    start_index = get_redis_state("start_index")
    cards = get_redis_state("cards")
    animation_class = get_redis_state("animation_class")

    for i in range(3):
        card_index = (start_index + i) % len(cards)
        card_class = animation_class[card_index]
        with cols[i]:
            st.markdown(f'<div class="{card_class}">{cards[card_index]}</div>', unsafe_allow_html=True)


st.divider()
dt1 = get_redis_state("dt1") or pd.DataFrame()  
dt2 = get_redis_state("dt2") or pd.DataFrame()  
dt3 = get_redis_state("dt3") or pd.DataFrame()  
dt4 = get_redis_state("dt4") or pd.DataFrame()  
bbox_coords = get_redis_state("bbox_coords") or []  

with st.form(key='df'):
    st.write("**Manually selected objects and their estimated heights.** (Double click on cells for editing the dataframes)") 
    expand = st.expander("Explanations") 
    expand.write("▶ The heights & widths of the objects will be used to calculate the total shadow area that could be cast by an obstacle.")
    expand.write("▶ Based upon the direction in which the object is situated respective to the site in consideration, we adjust the shadow dimensions automatically and recalculate total PV output based on partial shading.")
    
    c1, c2 = st.columns([1, 1])  
    
    with c1:      
        st.write("North:")
        dt1 = st.data_editor(dt1)
        set_redis_state("dt1", dt1)  

        st.write("West:")
        dt2 = st.data_editor(dt2)
        set_redis_state("dt2", dt2)  

    with c2:  
        st.write("South:")
        dt3 = st.data_editor(dt3)
        set_redis_state("dt3", dt3)  

        st.write("East:")
        dt4 = st.data_editor(dt4)
        set_redis_state("dt4", dt4)  

    re_estimate = st.form_submit_button("Re-Estimate Solar prediction", use_container_width=True)
    
    if re_estimate:
        bbox_coords = [[bbox_coords]]  # Update bbox_coords as needed
        main_df = pd.DataFrame({
            'bbox_coords': bbox_coords,
            'rect_height': 230,
            'line_height': 46,
            'estimated_height': 0
        })
        
        combined_df = combine_dataframes([main_df, dt1, dt2, dt3, dt4])
        set_redis_state("combined_df", combined_df)  
        set_redis_state("bbox_coords", bbox_coords)  
        
        switch_page('final')  # Navigate to final page



