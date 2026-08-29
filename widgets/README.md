# ClawOS Desktop Widgets

Agents push info to your desktop screen in real-time.

## How it works

1. Agent writes HTML to `/opt/clawos/widgets/current.html`
2. Chrome on desktop displays it fullscreen as overlay
3. Agent updates the file → screen updates instantly

## Usage

```bash
# Update desktop widget
echo '<h1>Meeting in 10 min</h1>' > /opt/clawos/widgets/current.html

# Show notification
echo '{"type":"alert","title":"Disk Alert","message":"80% full"}' > /opt/clawos/widgets/notification.json
```
