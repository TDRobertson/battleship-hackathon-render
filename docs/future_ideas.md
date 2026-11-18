# Future ideas

Things that have been discussed for the viewer but not built. None of them is
scheduled; this is a list to pick from.

## Dusk into night

Let the light change over the course of a match. The battle would open at
sunset, as it does now, and darken as it goes on, so that by the last few ships
the scene is lit mainly by the fires, the lighthouse beam and gun flashes.

What it would involve:

- **Sky.** The sky dome is a small shader that blends a horizon colour into a
  zenith colour and adds a sun glow. Driving those colours and the sun's height
  from match progress (shots fired divided by total shots) gives the sunset,
  twilight and night looks; stars can be a sprinkle of bright points that fade
  in.
- **Light.** Lower the sun and hemisphere light intensity on the same curve, and
  shift the sun colour from orange towards a dim blue moonlight so ships stay
  readable.
- **Water and haze.** The water shader and the distance haze both take the
  horizon colour, so they need the same value each frame to keep the horizon
  seamless.
- **Things that should glow.** Bridge windows, the lighthouse lamp and beam,
  fires, tracers and shell trails already use unlit or additive materials, so
  they will stand out more on their own. Navigation lights on ships and a
  brighter lighthouse beam would be cheap additions.
- **Readability.** The grids, hit markers and the AI-view heatmap are unlit and
  stay visible, but the ships themselves get dark. A floor on the ambient light
  is needed, and it should be checked in the vertical view as well as the wide
  one.

Open questions: whether the darkening should follow match progress or real
time, and whether the opening shots should stay at sunset regardless.

## Other ideas

- **A close-up on every sinking.** Currently a share of sinkings get the
  slow-motion close-up (`CINE_CHANCE`). Giving one to every ship adds roughly
  two seconds each.
- **Highlights mode.** A button that plays a condensed cut: the opening, a few
  close-ups and the finish.
- **Video export script.** Render a match frame by frame to an MP4 at an exact
  size, with the soundtrack rendered to match, so clips do not depend on screen
  recording.
- **End card.** Replace the plain winner card with club details and a link.
