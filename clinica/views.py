from django.shortcuts import render
from django.http import HttpResponse


def home(request):
    return render(request, 'home.html')


def agendamiento_view(request):
    return render(request, 'agendamiento.html')


def telemedicina_view(request):
    return render(request, 'telemedicina.html')
