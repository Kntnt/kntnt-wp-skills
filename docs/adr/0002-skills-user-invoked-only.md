# Both skills are user-invoked only

`clone` and `pull` set `disable-model-invocation: true`: they may be started solely by their slash command, never fired autonomously by the model. This is the correct safety posture because they execute code on production and overwrite the local database — an autonomous trigger of either would be an unacceptable blast radius for a convenience gain of nearly zero.
