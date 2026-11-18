from django.contrib.auth.views import LogoutView
from django.urls import path

from . import mother_views, views

app_name = "web"
urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/login/", views.ReachLoginView.as_view(), name="login"),
    path("accounts/logout/", LogoutView.as_view(next_page="web:home"), name="logout"),  # POST only
    path("app/", views.landing, name="landing"),
    path("app/switch-facility/", views.switch_facility, name="switch_facility"),
    path("app/clinician/", views.clinician, name="clinician"),
    path("app/chw/", views.chw, name="chw"),
    path("app/facility/", views.facility, name="facility"),
    path("app/county/", views.county, name="county"),
    path("app/system/", views.system, name="system"),
    path("mother/", mother_views.dashboard, name="mother_home"),
    path("mother/signin/", mother_views.signin, name="mother_signin"),
    path("mother/verify/", mother_views.verify, name="mother_verify"),
    path("mother/book/", mother_views.book, name="mother_book"),
    path("mother/cancel/", mother_views.cancel, name="mother_cancel"),
    path("mother/signout/", mother_views.signout, name="mother_signout"),    
]
