<?php

function updatePageing(array $page)
{
    if (array_key_exists("error", $page)) {
        return $page;
    }

    if (!array_key_exists("paging", $page)) {
        return $page;
    }
    if (!is_array($page["paging"])
        || (array_key_exists("cursors", $page["paging"]) && !is_array($page["paging"]["cursors"]))) {
        throw new RuntimeException("Graph API returned invalid paging metadata");
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

function loadGraphData(string|false $id, string $path, string|false $token, string $fields): array
{
    global $graph_api_url;

    if ($id === false || $id === "" || $token === false || $token === "") {
        throw new RuntimeException("Graph API credentials are not configured");
    }
    $context = stream_context_create(["http" => ["timeout" => 10]]);
    // Stream warnings include the credential-bearing URL; report a safe error instead.
    $json = @file_get_contents(
        sprintf($graph_api_url, $id, $path, $token, urlencode($fields)),
        false,
        $context
    );
    if ($json === false) {
        throw new RuntimeException("Graph API request failed");
    }
    try {
        $data = json_decode($json, true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException $error) {
        throw new RuntimeException("Graph API returned invalid JSON", 0, $error);
    }
    if (!is_array($data) || array_is_list($data)) {
        throw new RuntimeException("Graph API returned an invalid response");
    }
    if (array_key_exists("error", $data)) {
        throw new RuntimeException("Graph API returned an error");
    }
    if ($path !== "") {
        if (!isset($data["data"]) || !is_array($data["data"]) || !array_is_list($data["data"])) {
            throw new RuntimeException("Graph API returned invalid feed data");
        }
        $data = updatePageing($data);
    }
    return $data;
}


function loadPostFromInstagram()
{
    global $user_id, $user_token;

    try {
        $page = loadGraphData(
            $user_id,
            "/media",
            $user_token,
            "media_type, media_url, timestamp, permalink,caption, children{media_type, media_url}"
        );
        $metaData = loadGraphData($user_id, "", $user_token, "name,profile_picture_url");
        foreach (["id", "name", "profile_picture_url"] as $field) {
            if (!is_string($metaData[$field] ?? null)) {
                throw new RuntimeException("Graph API returned invalid Instagram profile data");
            }
        }

        returnJsonHttpResponse(true, [
            "id" => $metaData["id"],
            "name" => $metaData["name"],
            "profile_picture_url" => $metaData["profile_picture_url"],
            "media" => $page,
        ]);
    } catch (RuntimeException $error) {
        error_log("Instagram feed request failed: " . $error->getMessage());
        returnJsonHttpResponse(false, ["error" => "Unable to load Instagram posts."]);
    }
}

function loadPostsFromFacebook()
{
    global $page_id, $page_token;

    try {
        $page = loadGraphData(
            $page_id,
            "/posts",
            $page_token,
            "place,permalink_url,created_time,full_picture,id,attachments,message"
        );
        $metaData = loadGraphData($page_id, "", $page_token, "id,name,picture");
        if (!is_string($metaData["id"] ?? null) || !is_string($metaData["name"] ?? null)
            || !is_string($metaData["picture"]["data"]["url"] ?? null)) {
            throw new RuntimeException("Graph API returned invalid Facebook profile data");
        }

        returnJsonHttpResponse(true, [
            "id" => $metaData["id"],
            "name" => $metaData["name"],
            "picture" => $metaData["picture"],
            "posts" => $page,
        ]);
    } catch (RuntimeException $error) {
        error_log("Facebook feed request failed: " . $error->getMessage());
        returnJsonHttpResponse(false, ["error" => "Unable to load Facebook posts."]);
    }
}
