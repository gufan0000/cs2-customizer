#!/usr/bin/env bash
set -u
mkdir -p clips
: > clip_failed.txt
python -m pip install --disable-pip-version-check -q yt-dlp || true
fetch_clip() {
  local name="$1"
  local url="$2"
  echo "==> clip $name"
  yt-dlp --no-playlist -f 'best[height<=720]/best' --merge-output-format mp4 \
    --retries 3 --fragment-retries 3 \
    -o "clips/${name}.%(ext)s" "$url" || echo "$name | $url" >> clip_failed.txt
}
fetch_clip 01_known_sydney_awp4k 'https://clips.twitch.tv/SoftHomelyClipsdadOSsloth-JvR9SawSMte3_eb4'
fetch_clip 02_known_broky_clip 'https://clips.twitch.tv/IcySuccessfulFerretTakeNRG-kMd12Gi-7maX8yV9'
fetch_clip 03_secretive_goat 'https://clips.twitch.tv/SecretiveCharmingGoatDoggo'
fetch_clip 04_frail_toad 'https://clips.twitch.tv/FrailHilariousToadResidentSleeper'
fetch_clip 05_neighborly_card 'https://clips.twitch.tv/NeighborlyTransparentCardMcaT'
fetch_clip 06_blushing_triangle 'https://clips.twitch.tv/BlushingHilariousTriangleSaltBae-HK8usEWVKC3GiTWz'
fetch_clip 07_viscous_falcon 'https://clips.twitch.tv/ViscousSmilingFalconVoteNay-6bG9rk4v-oIqxKka'
fetch_clip 08_athletic_lark 'https://clips.twitch.tv/AthleticSecretiveLarkPrimeMe-CL8qDRbl0rMQuKrg'
fetch_clip 09_yummy_yogurt 'https://clips.twitch.tv/YummySpineyYogurtEagleEye-tm6LInklSbaLfAqk'
fetch_clip 10_polite_porpoise 'https://clips.twitch.tv/PoliteStupidPorpoiseKappaPride-cbs6Z8lNrGoDwBaV'
fetch_clip 11_spunky_durian 'https://clips.twitch.tv/SpunkyCoyDurianAllenHuhu-MNpJH2sKGpIvaxQh'
fetch_clip 12_delightful_lobster 'https://clips.twitch.tv/DelightfulSpikyLobsterCeilingCat-2WVtZiSW3yfZ4UmS'
find clips -maxdepth 1 -type f -printf '%f %s bytes\n' | sort
cat clip_failed.txt
