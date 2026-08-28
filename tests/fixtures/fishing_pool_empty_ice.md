# Fish-pool depletion regression sample

`fishing_pool_empty_ice.png` is the original, unmodified screenshot supplied by
the user on 2026-08-28. It includes the game title bar. Its central message reads
“水中暂时无鱼，将在17时10分后刷新”. The changing refresh time is not part of the
matching template.

The former full-screen Canny-edge matcher scores about 0.623 on this image,
below its old 0.72 threshold. Tests exercise both the original screenshot and
the client-area crop, plus generated background/opacity/scale variations and
negative samples. This one real map sample does not prove all maps work.
