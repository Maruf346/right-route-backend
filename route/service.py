from rest_framework.exceptions import ValidationError
import requests
from django.conf import settings
from core.models import AIExtractResponse

def extract_route_data(permit_file=None, permit_text=None):
        file_extract_url = "http://54.236.158.228:8001/api/ocr/extract"
        text_extract_url = "http://54.236.158.228:8001/api/ocr/extract-text"

        if permit_file:
            permit_file.seek(0)
            payload = {
                "file": (
                    permit_file.name,
                    permit_file.read(),
                    permit_file.content_type
                )
            }
        elif permit_text:
            payload = {
                "text": permit_text
            }
        else:
            raise ValidationError(
                "Permit file or Permit text must be need."
            )
        
        try:
            if permit_file:
                response = requests.post(
                    file_extract_url,
                    files=payload,
                    timeout=30
                )
            elif permit_text:
                response = requests.post(
                    text_extract_url,
                    data=payload,
                    timeout=30
                )
            print("response: ", response)
            if response.status_code != 200:
                raise ValidationError(
                    "Documents Extract Failed!"
                )
            response_data = response.json()
        
            if not response_data.get('success') and not response_data.get('route_information'):
                raise ValidationError(
                    "Documents Extract Failed!"
                )
            return response_data.get('route_information')
        except requests.exceptions.Timeout:
            raise ValidationError(
                "OCR server timeout."
            )
        except requests.exceptions.ConnectionError:
            raise ValidationError(
                "Cannot connect to OCR server."
            )
        except Exception as e:
            raise ValidationError(str(e))



def get_intersection_lat_lng(address_list: list):
        address_list_lat_lng = []
        for address in address_list:
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                "address": address,
                "key": settings.GOOGLE_MAP_API_KEY
                # "key": os.getenv("GOOGLE_MAP_API_KEY")
            }
            response = requests.get(url, params=params)
            AIExtractResponse.objects.create(response_json=str(response))
            data = response.json()
            AIExtractResponse.objects.create(response_json=str(data))
            
            if data["status"] == "OK":
                location = data["results"][0]["geometry"]["location"]
                address_lat_lng = {
                    "name": address,
                    "lat": location['lat'],
                    "lng": location['lng']
                }
                address_list_lat_lng.append(address_lat_lng)
        return address_list_lat_lng

