# Rehearsal: Film Lab studio

Gold: Benji Taylor's stageshow `examples/dark-hero`. Kept the neutral dark surface hierarchy, fine borders, restrained accent, and compact row rhythm. Adapted these to a working photo editor with existing real controls and user-owned samples. The photo remains fully contained and unfiltered; no fake cursor, placeholder controls, or cropped application frame is used.

States: official LUT with/without print material; C200 print/digital; Velvia slide scan; uploaded photo; comparison at 0/50/100%; Korean/English; saved language after reload; narrow-screen film selection and return to preview; V-Log export notice.

Captured and inspected through the in-app browser: 1440×900 desktop in Korean and English, 1366×768 laptop, 390×844 and 360×800 mobile. Rehearsal screenshots are workspace review artifacts, not public runtime assets. Representative frames: `modern-desktop-ko.png`, `modern-desktop-en.png`, `modern-mobile-en.png`, `modern-mobile-360-en.png`, `modern-mobile-export-en.png`, `modern-laptop-en.png`.

Review: an independent reviewer examined the KO desktop and EN mobile frames against stageshow's review/verify guidance. Findings and response:

- Film changes were not reachable from the first mobile screen → added a Films / 필름 고르기 button that focuses and scrolls to the library; selecting a film returns to the photo on mobile. Browser interaction verified.
- A Korean simulation label remained in English → translated and checked visible English DOM text for remaining Korean.
- A Korean explanatory sentence left a single character on its last line → shortened the copy while retaining the approximation notice.

Additional checks: no horizontal document overflow at 360/390/1440; export remains above the fold on desktop and fixed below the photo on mobile; extra bottom spacing keeps the last settings and source links reachable when the V-Log warning is displayed. The photo uses object-fit:contain; thumbnail brightness filters were removed. Keyboard comparison endpoints and visible focus were checked. SUIT and Manrope are served locally with their original licenses.

Validation: 35 meaningful tests cover LUT interpolation/transport, public filtering, country routing and locale preference priority including an in-flight manual override. Build verification checks the 238-look / 476-LUT public catalog and asset hashes. UI/language edits do not change the processing worker, LUT data, or color pipeline.

Assumptions: use one URL with a Korean or English interface, selected by the trusted Cloudflare country signal unless the user has chosen a language. Missing country data falls back to browser language. User-uploaded filenames remain unchanged.

Not checked: the gold example was reviewed as source, not rendered beside the app. The stageshow scripted film/gate tools were not run; this is an interactive application, verified through the supported browser interface, not an animated demo. No animation choreography was introduced. Reduced-motion CSS removes transitions, but an OS-level reduced-motion toggle was not exercised. Real iOS/Android hardware, camera LUT playback and film/print color accuracy are outside this design and localization pass.
