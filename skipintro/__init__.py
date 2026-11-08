"""Skip intro: an optional pak that shortens the startup screens of the game to a minimum.

The startup sequence of the title map stays the same (the game loads system data and saves during it); only
durations change, overwritten in place so that file sizes do not change:

- ``logo_spikechun.mp4`` is replaced by 0.2 s of black video;
- ``WBP_PictureCtrl`` (base of the Unreal logo and warning screens): ``ShowTime`` 6 s and fades 0.5 s;
- ``WBP_AutoSaveCaution``: ``ForcedShowTime`` 1 s.
"""
