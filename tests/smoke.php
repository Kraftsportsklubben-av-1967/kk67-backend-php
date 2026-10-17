<?php

set_error_handler(static function (int $severity, string $message, string $file, int $line): never {
    throw new ErrorException($message, 0, $severity, $file, $line);
});

$_SERVER["REQUEST_URI"] = "/";
$_SERVER["REQUEST_METHOD"] = "GET";

require __DIR__ . "/../src/index.php";

$error = ["error" => ["message" => "fixture"]];
if (updatePageing($error) !== $error) {
    throw new RuntimeException("Graph error response was not preserved");
}

$id = "123456789012345678901234567890";
$url = sprintf($graph_api_url, $id, "/posts", "fixture", "id");
if (!str_starts_with($url, "https://graph.facebook.com/v26.0/")) {
    throw new RuntimeException("Expected an explicit Graph API v26.0 request");
}
if (!str_contains($url, "/" . $id . "/posts/")) {
    throw new RuntimeException("Graph ID was not preserved as an opaque string");
}

$page = ["paging" => ["cursors" => ["before" => "first", "after" => "last"]]];
if (updatePageing($page) !== ["paging" => ["cursors" => []]]) {
    throw new RuntimeException("Unavailable paging cursors were not removed");
}

register_shutdown_function(static function (): void {
    if (ob_get_contents() !== '{"ok":true}') {
        fwrite(STDERR, "Expected a clean JSON response\n");
        exit(1);
    }
});

echo "Output that must not appear in the JSON response";
returnJsonHttpResponse(true, ["ok" => true]);
