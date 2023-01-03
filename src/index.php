<?php

$graph_api_url = "https://graph.facebook.com/v13.0/%d%s/?access_token=%s&fields=%s&limit=25";
$pagination_token = 1;

$page_id = getenv("FB_PAGE_ID");
$user_id = getenv("FB_USER_ID");
$user_token = getenv('FB_USER_KEY');
$page_token =  getenv('FB_PAGE_KEY');

require "loader.php";

header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST,GET,OPTIONS');
header('Access-Control-Allow-Headers: Origin, X-Requested-With, Content-Type, Accept');
header('Access-Control-Max-Age: 86400');    // cache for 1 day
header("Content-type: application/json; charset=utf-8");


$path = str_replace("/index.php", "", $_SERVER["REQUEST_URI"]);
$method = $_SERVER["REQUEST_METHOD"];


if ($path == "/posts/fb/" && $method == "GET") {
    loadPostsFromFacebook();
}

if ($path == "/posts/ig/" && $method == "GET") {
    loadPostFromInstagram();
}
