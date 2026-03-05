<?php

function updatePageing(array $page)
{
    if (in_array("error", $page)) {
        return $page;
    }

    if (!array_key_exists("previous", $page["paging"])) {
        unset($page["paging"]["cursors"]["before"]);
    }

    if (!array_key_exists("next", $page["paging"])) {
        unset($page["paging"]["cursors"]["after"]);
    }

    unset($page["paging"]["next"]);
    unset($page["paging"]["previous"]);

    return $page;
}

function returnJsonHttpResponse($success, $data)
{
    // remove any string that could create an invalid JSON
    // such as PHP Notice, Warning, logs...
    ob_clean();

    header("Content-type: application/json; charset=utf-8");

    if ($success) {
        http_response_code(200);
    } else {
        http_response_code(500);
    }
    
    echo json_encode($data, JSON_UNESCAPED_UNICODE);

    // making sure nothing is added
    exit();
}


function loadPostFromInstagram()
{
    global $graph_api_url, $user_id, $user_token;

    $json = @file_get_contents(
        sprintf(
            $graph_api_url,
            $user_id,
            "/media",
            $user_token,
            urlencode("media_type, media_url, timestamp, permalink,caption, children{media_type, media_url}")
        )
    );

    if ($json === false) {
        returnJsonHttpResponse(false, ["error" => "Failed to fetch Instagram media"]);
    }

    $page = json_decode($json, true);
    if (!is_array($page)) {
        returnJsonHttpResponse(false, ["error" => "Invalid response from Instagram API"]);
    }
    $page = updatePageing($page);
    $metaJson = @file_get_contents(
        sprintf(
            $graph_api_url,
            $user_id,
            "",
            $user_token,
            urlencode("name,profile_picture_url")
        )
    );

    if ($metaJson === false) {
        returnJsonHttpResponse(false, ["error" => "Failed to fetch Instagram profile"]);
    }

    $metaData = json_decode($metaJson, true);
    if (!is_array($metaData)) {
        returnJsonHttpResponse(false, ["error" => "Invalid response from Instagram profile API"]);
    }

    $response = [
        "id" => $metaData["id"],
        "name" => $metaData["name"],
        "profile_picture_url" => $metaData["profile_picture_url"],
        "media" => $page,
    ];

    returnJsonHttpResponse(true, $response);
}

function loadPostsFromFacebook()
{
    global $graph_api_url, $page_id, $page_token;

    $json = @file_get_contents(
        sprintf(
            $graph_api_url,
            $page_id,
            "/posts",
            $page_token,
            urlencode("place,permalink_url,created_time,full_picture,id,attachments,message")
        )
    );

    if ($json === false) {
        returnJsonHttpResponse(false, ["error" => "Failed to fetch Facebook posts"]);
    }

    $metaJson = @file_get_contents(
        sprintf(
            $graph_api_url,
            $page_id,
            "",
            $page_token,
            urlencode("id,name,picture")
        )
    );

    if ($metaJson === false) {
        returnJsonHttpResponse(false, ["error" => "Failed to fetch Facebook page metadata"]);
    }

    $metaData = json_decode($metaJson, true);

    $page = json_decode($json, true);
    if (!is_array($page)) {
        returnJsonHttpResponse(false, ["error" => "Invalid response from Facebook API"]);
    }
    $page = updatePageing($page);

    $response = [
        "id" => $metaData["id"],
        "name" => $metaData["name"],
        "picture" => $metaData["picture"],
        "posts" => $page,
    ];

    returnJsonHttpResponse(true, $response);
}
