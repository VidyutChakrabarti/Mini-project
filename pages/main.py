import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import ee 
from geopy.geocoders import Photon 
import threading
from streamlit.runtime.scriptrunner import add_script_run_ctx
from shapely.geometry import Polygon
from shapely.geometry import shape
from pyproj import Transformer
import shapely.ops as ops
from dotenv import load_dotenv
import os
from streamlit_extras.switch_page_button import switch_page
import asyncio
from helperfuncs import main_fetch
import redis
import pickle

load_dotenv()
api_key = os.getenv('SOLCAST_API_KEY')
st.set_page_config(layout="wide", page_title='SolarGis', page_icon = 'solargislogo.png')

ee.Initialize(project = 'ee-eventhorizon')


with open("style.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=False)
EXPIRATION_TIME = 1800  
def set_redis_state(key, value):
    redis_client.setex(key, EXPIRATION_TIME, pickle.dumps(value))

def get_redis_state(key, default_value=None):
    value = redis_client.get(key)
    return pickle.loads(value) if value else default_value


if get_redis_state('lat') is None:
    set_redis_state('lat', 21.1537)
if get_redis_state('lng') is None:
    set_redis_state('lng', 79.0729)
if get_redis_state('prev_rectangle_coords') is None:
    set_redis_state('prev_rectangle_coords', None)
if get_redis_state('total_area') is None:
    set_redis_state('total_area', 2.0)
if get_redis_state('bbox_center') is None:
    set_redis_state('bbox_center', None)
if get_redis_state('response_radiation') is None:
    set_redis_state('response_radiation', None)
if get_redis_state('response_pv_power') is None:
    set_redis_state('response_pv_power', None)
if get_redis_state('bbox_coords') is None: 
    set_redis_state('bbox_coords', None)
if get_redis_state('npanels') is None: 
    set_redis_state('npanels', 12)
if get_redis_state('panel_area') is None: 
    set_redis_state('panel_area', 1.95)

buildings = ee.FeatureCollection("GOOGLE/Research/open-buildings/v3/polygons") 
def get_rectangle_coordinates(data):
    if data and 'geometry' in data:
        coordinates = data['geometry']['coordinates'][0]
        return coordinates[:-1] 
    return []

st.sidebar.markdown('<h1 class="gradient-text">Solar Potential Prediction Estimate</h1>', unsafe_allow_html=True)

geolocator = Photon(user_agent="measurements")
with st.sidebar.form(key='my_form'):
    location_name = st.text_input("Enter a location name:")
    submit_button = st.form_submit_button(label='Search')

if submit_button:
    try:
        loc = geolocator.geocode(location_name)
    except Exception as e: 
        loc = None
        st.sidebar.write("""Geocoding API rate exceeded,
                          restrain from overusing open-source APIs. Reload and Try Again!""")
        
    if loc:
        set_redis_state('lat', loc.latitude)
        set_redis_state('lng', loc.longitude)
        print(f"Geocoding query processed, results: {loc.latitude} {loc.longitude}.")
    else:
        st.sidebar.write("Location not found. Please try another name.")
        set_redis_state('lat', 21.1537)
        set_redis_state('lng', 79.0729)


map_location = [get_redis_state('lat') , get_redis_state('lng')] 
m = folium.Map(location=map_location, zoom_start=17, tiles=None)
google_dark_tile = folium.TileLayer(
    tiles="https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",  #1yrs = s, t, r 
    attr='Google',
    name='Google Dark',
    max_zoom=21,
    subdomains=['mt0', 'mt1', 'mt2', 'mt3'],
)
google_dark_tile.add_to(m)
draw = Draw(
    export=False,
    draw_options={
        'rectangle': True,
        'polyline': False,
        'polygon': False,
        'circle': False,
        'marker': False,
        'circlemarker': False,
    },
    edit_options={
        'edit': True, 
        'remove': True 
    }
)
draw.add_to(m)
def add_feature_collection_to_map(m):
    buildings_image = ee.Image().paint(featureCollection=buildings, color='ffcc00', width=1)
    visualization_params = {
        'min': 0,
        'max': 1,
        'palette': ['#ffcc00']}
    map_id_dict = buildings_image.getMapId(visualization_params)
    folium.TileLayer(
        tiles=map_id_dict['tile_fetcher'].url_format,
        attr='Google Earth Engine',
        name='Solar Potential - Building Footprints',
        overlay=True,
        control=True
    ).add_to(m)

add_feature_collection_to_map(m)

def set_npanels(): 
    total_area = get_redis_state('total_area')
    panel_area = get_redis_state('panel_area')
    
    if total_area >= panel_area:
        npanels = min(100, int(total_area // panel_area))
        set_redis_state('npanels', npanels)
        print("no. of panels", npanels)
    else:
        set_redis_state('npanels', 4)
    st.sidebar.write(f"**No. of max panels: {get_redis_state('npanels')}**")

def calculate_area(buildings_in_bbox):
    areas = buildings_in_bbox.aggregate_sum('area_in_meters').getInfo()
    set_redis_state('total_area', areas)
    print("rooftop area", areas)
    set_npanels()
    st.sidebar.write(f"**Rooftop area calculated: {get_redis_state('total_area')}**")


def threaded_calculate_area(buildings_in_bbox):
    thread = threading.Thread(target=calculate_area, args=(buildings_in_bbox,))
    add_script_run_ctx(thread)
    thread.start()

output = st_folium(m, width='100%')
if output.get('all_drawings') and isinstance(output.get('all_drawings'), list):
    if len(output['all_drawings']) == 1:
        drawing = output['all_drawings'][0]
        if drawing['geometry']['type'] == 'Polygon':
            rectangle_coords = get_rectangle_coordinates(drawing)
            if rectangle_coords:
                st.sidebar.markdown("### Selected Coordinates:")
                sides = ["Top-Left", "Top-Right", "Bottom-Right", "Bottom-Left"]
                for side, coord in zip(sides, rectangle_coords):
                    st.sidebar.markdown(f"**{side}:** `{coord}`")
                
                if rectangle_coords != get_redis_state('prev_rectangle_coords'):
                    bbox_coords = [i for i in rectangle_coords]
                    bbox_polygon = Polygon(bbox_coords)
                    transformer = Transformer.from_crs("epsg:4326", "epsg:6933", always_xy=True)
                    transformed_polygon = ops.transform(transformer.transform, bbox_polygon)
                    area = transformed_polygon.area
                    print("geodesic area", area)
                    
                    if area > 8000:
                        st.sidebar.markdown("<span style='color:red'>Area constraint violated. Choose a smaller area.</span>", unsafe_allow_html=True)
                    else:
                        set_redis_state('prev_rectangle_coords', rectangle_coords)               
                        bounding_box = ee.Geometry.Polygon([rectangle_coords])              
                        buildings_in_bbox = buildings.filterBounds(bounding_box)
                        calculate_area(buildings_in_bbox)  
                        set_redis_state('bbox_center', bbox_polygon.centroid.coords[0])
                        set_redis_state('bbox_coords', bbox_coords)
    else:
        st.sidebar.markdown("<span style='color:red'>Delete the previously selected bounding box.</span>", unsafe_allow_html=True)       
else:
    st.sidebar.write("Draw a bounding box over the area you want the solar estimation for.") 
    set_redis_state('total_area', 0)
    set_redis_state('bbox_center', None)
    set_redis_state('bbox_coords', None)

with st.sidebar.form(key='paraform', clear_on_submit=True):
    solar_efficiency = st.slider("Solar panel efficiency (%):", 0, 100, get_redis_state('solar_efficiency', 24))
    array_type = st.selectbox("Array Type:", ["Fixed (open rack)", "Tracking"], index=0 if get_redis_state('array_type') is None else 1 if get_redis_state('array_type') == "Tracking" else 0)
    
    est = st.form_submit_button(label='Estimate')

    if est and get_redis_state('bbox_center') is not None:
        bbox_center = get_redis_state('bbox_center')
        latitude = bbox_center[1]
        longitude = bbox_center[0]

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response_radiation, response_pv_power = loop.run_until_complete(main_fetch(latitude, longitude, api_key, int(get_redis_state('npanels'))))
            resp = response_pv_power['estimated_actuals']
        except Exception as e:
            st.error('Error fetching data from APIs')
            response_radiation, response_pv_power = None, None

        if response_radiation and response_pv_power:
            set_redis_state('response_radiation', response_radiation)
            set_redis_state('response_pv_power', response_pv_power)
            switch_page("app")

    if est and get_redis_state('bbox_center') is None: 
        st.sidebar.error("Select a bounding box")


with st.sidebar.form(key='panelsize'):
    panel_area = get_redis_state('panel_area')
    panel_size = st.number_input("Specify panel size in sq meters", min_value=1.0, max_value=3.0, value=panel_area, step=0.05)
    setsize = st.form_submit_button("Set Panel size")
    
    if setsize: 
        set_redis_state('panel_area', float(panel_size))
        set_npanels()  # Update number of panels based on the new panel area
        st.success(f"Panel size set to {get_redis_state('panel_area')}")

with st.sidebar.form(key='np'):
    npanels = get_redis_state('npanels')
    solar_panels = st.slider("Select number of solar panels installed:", min_value=1, max_value=400, value=npanels)
    setnp = st.form_submit_button("Set no. of Panels")
    
    if setnp: 
        set_redis_state('npanels', int(solar_panels))
        st.success(f"No. of panels set to {get_redis_state('npanels')}")
