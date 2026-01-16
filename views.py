from django.http import JsonResponse
from .models import Book

def inventory_view(request):
    books = list(Book.objects.values())
    return JsonResponse(books, safe=False)
