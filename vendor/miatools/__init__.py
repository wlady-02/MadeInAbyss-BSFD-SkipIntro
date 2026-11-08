"""Shared tools for Made in Abyss: Binary Star Falling into Darkness mods.

Modules:
    audit   -- what is not committed, pushed, tracked or in its place
    config  -- local configuration (``shared/paths.local.toml``) and environment overrides
    paths   -- every game, Proton and backup path, resolved once
    game    -- whether the game is running
    modfolders -- one visible folder per mod: mods/<slug> is a worktree of project/<slug>
    hub     -- the one change to main a mod session pushes directly: its row of PROJECTS.md
    saves   -- save slots and their backups
    ue4ss   -- UE4SS log, crash reports, installing UE4SS Lua mods
    pak     -- reading and writing .pak files, reading files from the official game paks
    release -- release checks, self-contained copy of miatools, release zip
    uasset  -- reading names, imports and exports of cooked .uasset files
"""
