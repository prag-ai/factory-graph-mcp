#!/bin/zsh
# README 그림 만들기: docs/images/src/*.svg → docs/images/*.png|jpg
# 필요한 것: resvg, Pretendard·D2Coding TTF 가 든 폴더 (FONTS 환경 변수)
set -e
HERE=${0:A:h}
FONTS=${FONTS:?Pretendard·D2Coding TTF 폴더를 FONTS 에 지정하세요}
cd $HERE/src
for svg in *.svg; do
  name=${svg%.svg}
  resvg --skip-system-fonts --use-fonts-dir $FONTS --font-family Pretendard --background white -w 1600 $svg $HERE/$name.png
  if [[ $name != hero ]]; then   # 사진이 든 그림은 JPG로
    sips -s format jpeg -s formatOptions 85 $HERE/$name.png --out $HERE/$name.jpg >/dev/null && rm $HERE/$name.png
  fi
  echo "$svg → $(ls $HERE/$name.*)"
done
