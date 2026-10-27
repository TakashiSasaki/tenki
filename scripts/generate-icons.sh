#!/bin/sh
set -eu
# Inkscape 1.4; regenerate checked-in PNGs from original SVG sources.
for size in 192 512; do
  inkscape assets/icon.svg --export-type=png --export-width="$size" --export-height="$size" --export-filename="static/icons/icon-$size.png"
done
for size in 180 32; do
  inkscape assets/icon.svg --export-type=png --export-width="$size" --export-height="$size" --export-filename="static/icons/icon-$size.png"
done
inkscape assets/social.svg --export-type=png --export-width=1200 --export-height=630 --export-filename=static/icons/social.png
