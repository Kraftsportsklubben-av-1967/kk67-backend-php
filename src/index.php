<?php

require "loader.php";

$graph_api_url = "https://graph.facebook.com/v13.0/%d%s/?access_token=%s&fields=%s&limit=25";
$pagination_token = 1;

$page_id = getenv("FB_PAGE_ID");
$user_id = getenv("FB_USER_ID");
$user_token = getenv('FB_USER_KEY');
$page_token =  getenv('FB_PAGE_KEY');



$path = $_SERVER["REQUEST_URI"];

if ($path == "/posts/fb") {
    loadPostsFromFacebook();
}

if ($path == "/posts/ig") {
    loadPostFromInstagram();
}



?>