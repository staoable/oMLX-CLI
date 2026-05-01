export async function readSseEvents(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const events = buf.split("\n\n");
    buf = events.pop();
    for (const rawEvent of events) {
      const lines = rawEvent.split("\n");
      let eventType = "message";
      let data = "{}";
      for (const line of lines) {
        if (line.startsWith("event:")) eventType = line.slice(6).trim();
        if (line.startsWith("data:")) data = line.slice(5).trim();
      }
      let parsed = {};
      try {
        parsed = JSON.parse(data || "{}");
      } catch {
        continue;
      }
      onEvent(eventType, parsed);
    }
  }
}
