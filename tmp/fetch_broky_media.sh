#!/usr/bin/env bash
set -u
mkdir -p assets videos
: > failed.txt

download() {
  local name="$1"
  local url="$2"
  local referer="${3:-https://www.google.com/}"
  echo "==> $name"
  if ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 180 \
    -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36" \
    -e "$referer" "$url" -o "assets/$name"; then
    echo "$name | $url" >> failed.txt
    rm -f "assets/$name"
  fi
}

download 01_epsilon_portrait.jpg 'https://img-cdn.hltv.org/gallerypicture/sd8GKheTIx-vs02zNb7lG3.jpg?auto=compress&ixlib=java-2.1.0&q=75&s=2f0e52b1796a7005a5b9283fd387d2e1&w=1200' 'https://www.hltv.org/'
download 02_faze_announcement_2019.jpg 'https://pbs.twimg.com/media/EFaPQBHWwAER31X.jpg' 'https://x.com/'
download 03_epsilon_pc.jpg 'https://static.draft5.gg/news/2019/11/25155719/Epsilon-broky-Charleroi-Esports-2019.jpeg' 'https://draft5.gg/'
download 04_antwerp_broky_trophy.jpg 'https://esportsinsider.com/wp-content/uploads/2025/07/Who-is-broky-large.jpg' 'https://esportsinsider.com/'
download 05_antwerp_crowd.jpg 'https://static.lsm.lv/media/2022/05/large/2/i2pw.jpg' 'https://www.lsm.lv/'
download 06_katowice_team.jpg 'https://www.talkesport.com/wp-content/uploads/PpAWJlgjAUKXwLrh_Qhq9e.jpg' 'https://www.talkesport.com/'
download 07_katowice_trophy.jpg 'https://img.redbull.com/images/q_auto%2Cf_auto/redbullcom/2022/2/28/sxajti5q2skdilslqgzy/faze-iem-katowice-2022' 'https://www.redbull.com/'
download 08_cologne_team.jpg 'https://www.hotspawn.com/wp-content/uploads/2022/07/FaZe-win-Cologne-Helena-Kristiansson-1.jpg' 'https://www.hotspawn.com/'
download 09_grandslam.jpg 'https://cdn.payga.me/blog/image/2023/03/26/dasa.jpg' 'https://payga.me/'
download 10_sydney.jpg 'https://cdn.sanity.io/images/zoz4y99f/production/13dd5e4fe5f400b4bc3ec0c1429084d6c98ca201-2000x1125.jpg?auto=format&w=2000' 'https://www.eslfaceitgroup.com/'
download 11_chengdu_mvp.jpg 'https://img-cdn.hltv.org/gallerypicture/olP7003NKiHrIELWW9nTIK.jpg?auto=compress&ixlib=java-2.1.0&q=75&s=90254acc4810e0062c4863028f99cf83&w=1600' 'https://www.hltv.org/'
download 12_shanghai_defeat.jpg 'https://prod.assets.earlygamecdn.com/images/karrigan-Major-FInal-Shanghai-2024.jpeg?transform=Article+Webp' 'https://earlygame.com/'
download 13_shanghai_team.jpg 'https://static.draft5.gg/news/2024/12/13141212/FaZe-Clan-rain-frozen-e-karrigan-Perfect-World-Shanghai-Major-2024.jpg' 'https://draft5.gg/'
download 14_benched_2025.jpg 'https://media.esports.gg/uploads/2025/05/Broky-benched.jpg' 'https://esports.gg/'
download 15_return_2025.webp 'https://egw.news/uploads/news/1/17/1752076041150_1752076041150.webp' 'https://egw.news/'
download 16_budapest_shout.jpg 'https://static.draft5.gg/news/2025/12/08173112/FaZe-Clan-broky-StarLadder-Budapest-Major-2025-3.jpg' 'https://draft5.gg/'
download 17_budapest_final.jpg 'https://img-cdn.hltv.org/gallerypicture/uBdmOUdUplM2oXGfDx0i5A.jpg?auto=compress&ixlib=java-2.1.0&m=%2Fm.png&mw=80&mx=15&my=355&q=75&s=bf3accdfe6d3b095ca3f1c432ec3da7a&w=600' 'https://www.hltv.org/'
download 18_bench_2026_thankyou.jpg 'https://oss.5eplay.com/editor/20260626/109407feddbb11b1309f570724b25f6f.jpg' 'https://csgo.5eplay.com/'
download 19_broky_2026.jpg 'https://img-cdn.hltv.org/gallerypicture/O7a9SI_BCbnkBrS0BkMVl7.jpg?auto=compress&ixlib=java-2.1.0&m=%2Fm.png&mw=107&mx=20&my=474&q=75&s=5d237c609f819adace5a2c945cd40812&w=800' 'https://www.hltv.org/'
download 20_faze_lowpoint.jpg 'https://img-cdn.hltv.org/gallerypicture/zzbUCiTNmbRiFRgyWvkT6y.jpg?auto=compress&ixlib=java-2.1.0&m=%2Fm.png&mw=160&mx=30&my=710&q=75&s=187500568473914fda4186069bc4398c&w=1200' 'https://www.hltv.org/'

python -m pip install --disable-pip-version-check -q yt-dlp || true
fetch_video() {
  local name="$1"
  local url="$2"
  echo "==> video $name"
  yt-dlp --no-playlist --concurrent-fragments 4 \
    -f 'bv*[height<=720]+ba/b[height<=720]' --merge-output-format mp4 \
    --retries 3 --fragment-retries 3 \
    -o "videos/${name}.%(ext)s" "$url" || echo "VIDEO FAILED: $name $url" >> failed.txt
}
fetch_video 2021_interlude 'https://www.youtube.com/watch?v=o0yd9cT7vIE'
fetch_video 2022_antwerp_final 'https://www.youtube.com/watch?v=MsfC8T5JR4I'
fetch_video 2024_chengdu_mvp 'https://www.youtube.com/watch?v=2FD1pA6W-V8'
fetch_video 2026_goodbye 'https://www.youtube.com/watch?v=EB0Z8VTW8CA'

echo 'Downloaded images:'
find assets -maxdepth 1 -type f -printf '%f %s bytes\n' | sort
echo 'Downloaded videos:'
find videos -maxdepth 1 -type f -printf '%f %s bytes\n' | sort
echo 'Failures:'
cat failed.txt
