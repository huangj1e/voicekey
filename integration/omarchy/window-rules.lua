-- VoiceKey's transparent overlay windows supply their own rounded surfaces.
o.window({ class = "^voicekey$", title = "^(hud|pick)$" }, {
  border_size = 0,
  rounding = 0,
  no_shadow = true,
  no_blur = true,
})
-- The HUD is informational and should never take focus from the input field.
o.window({ class = "^voicekey$", title = "^hud$" }, { no_focus = true })
