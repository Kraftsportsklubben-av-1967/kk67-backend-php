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


function loadPostFromInstagram()
{
    global $graph_api_url, $user_id, $user_token;

    $json = file_get_contents(
        sprintf(
            $graph_api_url,
            $user_id,
            "/media",
            $user_token,
            urlencode("media_type, media_url, timestamp, permalink,caption, children{media_type, media_url}")
        )
    );

    $page = json_decode($json, true);
    $page = updatePageing($page);
    $metaData =  json_decode(
        file_get_contents(
            sprintf(
                $graph_api_url,
                $user_id,
                "",
                $user_token,
                urlencode("name,profile_picture_url")
            )
        ),
        true
    );

    $response = [
        "id" => $metaData["id"],
        "name" => $metaData["name"],
        "profile_picture_url" => $metaData["profile_picture_url"],
        "media" => $page,
    ];

    print_r(json_encode($response));
}

function loadPostsFromFacebook()
{
    global $graph_api_url, $page_id, $page_token;

    $json = file_get_contents(
        sprintf(
            $graph_api_url,
            $page_id,
            "/posts",
            $page_token,
            urlencode("place,permalink_url,created_time,full_picture,id,attachments,message")
        )
    );

    $metaData =  json_decode(
        file_get_contents(
            sprintf(
                $graph_api_url,
                $page_id,
                "",
                $page_token,
                urlencode("id,name, picture")
            )
        ),
        true
    );

    $page = json_decode($json, true);
    $page = updatePageing($page);

    $response = [
        "id" => $metaData["id"],
        "name" => $metaData["name"],
        "picture" => $metaData["picture"],
        "posts" => $page,
    ];

    print_r(json_encode($response));
}
?>