from django.shortcuts import render
from rest_framework.generics import GenericAPIView
from .serializers import GetStartingWaypiontSerializer
from rest_framework.response import Response
import osmnx as ox
import requests


import re
import osmnx as ox
from shapely.ops import nearest_points
from shapely.geometry import Point
from django.conf import settings

def parse_location_string(text):
    """
    ইনপুট স্ট্রিং থেকে Road, Distance, Direction, এবং Town আলাদা করা।
    Example: "I-94, 2.8mi NW of Beach"
    """
    # Regex pattern to match: Road, Distance[mi/miles/km] Direction of Town
    pattern = r"^(.*?),\s*([\d.]+)\s*(?:mi|miles|km|kilometers)\s+([A-Z]{1,2})\s+of\s+(.*)$"
    match = re.match(pattern, text.strip(), re.IGNORECASE)
    
    if not match:
        raise ValueError("Invalid format! Expected format: 'Road, Distance mi Direction of Town' (e.g., 'I-94, 2.8mi NW of Beach')")
    
    road = match.group(1).strip()
    distance = float(match.group(2))
    direction = match.group(3).upper()
    town = match.group(4).strip()
    
    # Convert to meters (assuming input is in miles for US DOT permits)
    distance_meters = distance * 1609.34 
    
    return road, distance_meters, direction, town

def get_lat_lng(location_string):
    """
    মেইন ফাংশন: স্ট্রিং ইনপুট নিয়ে Lat/Lng রিটার্ন করবে।
    """
    try:
        # ১. স্ট্রিং পার্স করা
        road, dist_m, direction, town = parse_location_string(location_string)
        print(f"🔍 Parsing: Road='{road}', Dist={dist_m}m, Dir='{direction}', Town='{town}'")
        
        # ২. Town এর Center Coordinate বের করা (Nominatim via OSMnx)
        gdf = ox.geocode_to_gdf(f"{town}, USA")
        if gdf.empty:
            return None, "Town not found!"
        town_center = gdf.iloc[0].geometry.centroid
        
        # ৩. Road এর Geometry বের করা (OSM Overpass API)
        # US হাইওয়ের জন্য 'name' এর বদলে 'ref' ট্যাগ বেশি কাজ করে (যেমন: I-94, US-10)
        ref_tag = road.replace('I-', 'I ').replace('US-', 'US ').replace('CR-', 'CR ').replace('-', ' ')
        
        gdf_road = ox.features_from_point(
            (town_center.y, town_center.x),
            tags={'highway': ['motorway', 'trunk', 'primary', 'secondary'], 'ref': ref_tag},
            dist=10000 # 10km radius
        )
        
        # যদি 'ref' এ না পায়, 'name' দিয়ে ট্রাই করা
        if gdf_road.empty:
            gdf_road = ox.features_from_point(
                (town_center.y, town_center.x),
                tags={'highway': True, 'name': road},
                dist=10000
            )
            
        if gdf_road.empty:
            return None, f"Road '{road}' not found near {town}!"
            
        # সব লাইন একসাথে মার্জ করা এবং সবচেয়ে বড় লাইনটি (Main Highway) নেওয়া
        road_lines = gdf_road.geometry.unary_union
        if road_lines.geom_type == 'MultiLineString':
            road_lines = max(road_lines.geoms, key=lambda line: line.length)
            
        # ৪. Town Center থেকে Road এর সবচেয়ে কাছের পয়েন্ট (Anchor/Junction) বের করা
        anchor = nearest_points(town_center, road_lines)[1]
        proj_dist = road_lines.project(anchor)
        
        # ৫. Direction অনুযায়ী রোড ধরে সামনে বা পিছনে যাওয়া
        # (সিম্পল লজিক: N/NE/E/SE হলে ফরোয়ার্ড, বাকিগুলো ব্যাকওয়ার্ড)
        move_forward = direction in ['N', 'NE', 'E', 'SE']
        
        if move_forward:
            target_dist = proj_dist + dist_m
        else:
            target_dist = proj_dist - dist_m
            
        # রোডের লেন্থের বাইরে চলে না যায় তার জন্য ক্ল্যাম্প করা
        target_dist = max(0, min(target_dist, road_lines.length))
        
        # ৬. এক্সাক্ট পয়েন্ট ইন্টারপোলেট করা (Snap-to-road)
        final_point = road_lines.interpolate(target_dist)
        
        lat = final_point.y
        lng = final_point.x
        
        return (lat, lng), "Success"
        
    except Exception as e:
        return None, f"Error: {str(e)}"

class GetStartingWaypointViews(GenericAPIView):
    serializer_class = GetStartingWaypiontSerializer
    
    def get(self, request, *args, **kwargs):
        # serializer = GetStartingWaypiontSerializer(data=request.data)
        # serializer.is_valid(raise_exception=True)
        # location = serializer.validated_data["location"]
        return Response(
            {
                "success": True,
                # "location": location,
                "point": f"lat,lng"
            }
        )
    
    def get_lat_lng(self, location):
        print("start geocode: ")
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "address": location,
            "key": settings.GOOGLE_MAP_API_KEY
        }
        response = requests.get(url, params=params)
        print("response: ", response)
        data = response.json()
        print("data: ", data)
        address_lat_lng = None
        if data["status"] == "OK":
            location = data["results"][0]["geometry"]["location"]
            return {
                "lat": location['lat'],
                "lng": location['lng']
            }
        else:
            return None
        
    def post(self, request, *args, **kwargs):
        serializer = GetStartingWaypiontSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        location = serializer.validated_data["location"]
        
        # try:
        #     graph = ox.graph_from_place(
        #         location,
        #         network_type="drive"
        #     )
        # except:
        #     graph = None
        print("location: ", location)
        
        # result, status = get_lat_lng(location)
        # lat, lng = result
        # print("SUCCESS!")
        # print(f"Location: {location}")
        # print(f"Latitude:  {lat:.6f}")
        # print(f"Longitude: {lng:.6f}")
        # map_link = f"https://www.google.com/maps?q={lat},{lng}"
        
        lat_lng = self.get_lat_lng(location)
        result = f"{lat_lng.get("lat")},{lat_lng.get("lng")}" 
        map_link = f"https://www.google.com/maps?q={lat_lng.get("lat")},{lat_lng.get("lng")}"
        
        return Response(
            {
                "success": True,
                "location": location,
                # "point": f"{graph}",
                "lat-lng": result,
                "Google Maps Link": map_link
            }
        )
        
