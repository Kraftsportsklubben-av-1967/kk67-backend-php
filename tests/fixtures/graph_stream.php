<?php

class GraphFixtureStream
{
    public $context;
    private string $body = "";
    private int $offset = 0;

    public function stream_open($path, $mode, $options, &$opened_path): bool
    {
        if (parse_url($path, PHP_URL_HOST) !== "graph.facebook.com") {
            throw new RuntimeException("Unexpected fixture host");
        }
        $fixture = json_decode(file_get_contents(getenv("GRAPH_FIXTURE_FILE")), true, 512, JSON_THROW_ON_ERROR);
        $kind = preg_match("~/(media|posts)/~", parse_url($path, PHP_URL_PATH)) ? "feed" : "profile";
        $context = is_resource($this->context) ? stream_context_get_options($this->context) : [];
        file_put_contents(getenv("GRAPH_REQUEST_LOG"), json_encode([
            "kind" => $kind,
            "timeout" => $context["http"]["timeout"] ?? null,
        ]) . "\n", FILE_APPEND);
        if (!$fixture[$kind]["available"]) {
            return false;
        }
        $this->body = $fixture[$kind]["body"];
        return true;
    }

    public function stream_read($count): string
    {
        $chunk = substr($this->body, $this->offset, $count);
        $this->offset += strlen($chunk);
        return $chunk;
    }

    public function stream_eof(): bool
    {
        return $this->offset >= strlen($this->body);
    }

    public function stream_stat(): array
    {
        return [];
    }
}

if (in_array("https", stream_get_wrappers(), true)) {
    stream_wrapper_unregister("https");
}
stream_wrapper_register("https", GraphFixtureStream::class);
