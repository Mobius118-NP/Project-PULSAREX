# Brutalist signal terminal

The user-supplied palette is implemented in `dashboard/terminal.css`, loaded after
the existing responsive layout styles. Charts use the corresponding palette in
`app.js`. Surfaces are flat; corners are square; shadows, glow and decorative
gradients are removed. The spectrum fill is a uniform translucent olive.

| Token | Color | Use |
|---|---|---|
| Chassis black | `#101310` | Page, top bar, secondary surfaces |
| Instrument black | `#090C09` | Plot panels, camera window, dialogs |
| Panel grey | `#202620` | Headers, controls, status strips |
| Divider grey | `#485047` | Structural borders |
| Phosphor olive | `#A2BE91` | Current spectrum, primary bearing, primary controls |
| Industrial amber | `#D8AC58` | Baseline, alternate bearing, caution |
| Signal white | `#D1D5CC` | Primary text and independent visual vectors |
| Fault red | `#BA5548` | Faults and destructive controls |
| Muted text | `#899187` | Supporting labels |
| Plot grid | `#293129` | Scientific plot grid and subtle internal divisions |

The primary font is **IBM Plex Sans**. Numeric readouts, tables, plot labels and
other instrument text use **IBM Plex Mono**. Both are bundled locally in
`dashboard/fonts` and are served by the same local server; no runtime font CDN
or external account is used. The Google Fonts upstream sources are
[IBM Plex Sans](https://github.com/google/fonts/tree/main/ofl/ibmplexsans) and
[IBM Plex Mono](https://github.com/google/fonts/tree/main/ofl/ibmplexmono).
Their SIL Open Font License notices are included beside the font files.

The [signed frequency-shift color scale](frequency-shift-indicator.md) retains its
continuous blue/violet → green → red mapping and legend. This is measurement
encoding, separate from flat interface decoration. Spectrogram intensity also
retains its continuous data mapping, using the new palette. Its compact legend
uses flat color bands. Acoustic and visual vectors remain separately labelled;
changing presentation does not add range or sound-source identification.
