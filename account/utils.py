from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework import status
from rest_framework.exceptions import ValidationError

class OwnAPIView(APIView):
    serializer_class = None

    def get_serializer(self, *args, **kwargs):
        """Return serializer instance. Accepts arbitrary args/kwargs and
        ensures a default `context` containing the request is provided,
        matching DRF's GenericAPIView behavior so external callers
        (like schema generators) can call with `context=`.
        """
        if not self.serializer_class:
            return None

        kwargs.setdefault("context", {})
        # ensure request is available in context
        if "request" not in kwargs["context"]:
            kwargs["context"]["request"] = getattr(self, "request", None)

        return self.serializer_class(*args, **kwargs)
    
    def success_response(self, serializer):
        return Response(
            {
                "success": True,
                "detail": ""
            }, status=status.HTTP_200_OK
        )

    def post(self, request, *args, **kwargs) -> Response:
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return self.success_response(serializer)
        except ValidationError:
            error = {key: str(value[0]) for key, value in serializer.errors.items()}
            return Response(
                {
                    "success": False,
                    "detail": error
                }, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "detail": str(e)
                }, status=status.HTTP_400_BAD_REQUEST
            )


