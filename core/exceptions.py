from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status as drf_status


def _first_error(value):
    if isinstance(value, dict):
        for nested in value.values():
            detail = _first_error(nested)
            if detail:
                return detail
        return ""
    if isinstance(value, (list, tuple)):
        return _first_error(value[0]) if value else ""
    return str(value) if value is not None else ""

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        detail = ""
        if isinstance(response.data, dict):
            detail = _first_error(response.data.get("detail")) or _first_error(response.data)
        else:
            detail = _first_error(response.data)
        print("detail: ", detail)
        custom_response = {
            "status": False,
            "detail": detail
        }
        response.data = custom_response
    else:
        return Response(
            {"status": False, "detail": str(exc)},
            status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    return response

