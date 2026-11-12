from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def success(data=None, status=200):
    return Response({"success": True, "data": data, "error": None}, status=status)


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None:
        response.data = {"success": False, "data": None, "error": response.data}
    return response
