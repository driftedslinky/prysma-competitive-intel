"""Seed the database with Round Timer competitors."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prysma.storage.database import db

COMPETITORS = [
    {
        "name": "Interval Timer",
        "website": "https://play.google.com/store/apps/details?id=cc.dreamspark.intervaltimer",
        "description": "The dominant Android interval timer. 269K ratings, 4.9★. Simple, full-screen color coding. Common complaint: timer stops on screen lock.",
        "platforms": {"android": "cc.dreamspark.intervaltimer"},
    },
    {
        "name": "Tabata Timer",
        "website": "https://play.google.com/store/apps/details?id=com.evgeniysharafan.tabatatimer",
        "description": "Tabata-focused Android timer. 227K ratings, 4.9★. 50+ sounds. Complex UI, overwhelming for beginners.",
        "platforms": {"android": "com.evgeniysharafan.tabatatimer", "ios": "id1255964203"},
    },
    {
        "name": "Seconds Interval Timer",
        "website": "https://www.intervaltimer.com/",
        "description": "Powerhouse free interval timer. iOS + Android + Web. 71K ratings, 4.7★. Free limited to 1 saved timer. One-time Pro upgrade $4.99.",
        "platforms": {"android": "com.runloop.seconds.free", "ios": "id475816966"},
    },
    {
        "name": "Intervals Pro",
        "website": "https://apps.apple.com/us/app/intervals-pro-hiit-timer/id957586938",
        "description": "Apple Watch HIIT timer. iOS only. Free + $9.99 one-time or $4.99/mo. Polished watchOS experience. Voice prompts.",
        "platforms": {"ios": "id957586938"},
    },
    {
        "name": "Box Timer",
        "website": "https://boxtimer.app/",
        "description": "Completely free, ad-free workout timer. iOS. 4,030 ratings, 4.9★. Three timer modes. Donation-supported.",
        "platforms": {"ios": "id1547518531"},
    },
    {
        "name": "SmartWOD",
        "website": "https://smartwod.app/",
        "description": "WOD generator + timer. 6M+ downloads, 140K+ 5-star reviews. Free + premium ($89.99 lifetime or $9.99/mo). Apple Watch.",
        "platforms": {"android": "net.smartwod.workouts", "ios": "id1317933303"},
    },
    {
        "name": "Boxing Round Interval Timer",
        "website": "https://play.google.com/store/apps/details?id=kr.co.royzero.boxingtimer",
        "description": "Boxing-specific Android timer. 47K ratings, 4.7★. Free. No iOS version.",
        "platforms": {"android": "kr.co.royzero.boxingtimer"},
    },
    {
        "name": "PushPress Timer",
        "website": "https://www.pushpress.com/workout-timer/interval-timer",
        "description": "Gym/coach-focused timer. iOS + Apple TV. Free. Apple TV output for group fitness.",
        "platforms": {"ios": "id1554256831"},
    },
    {
        "name": "Interval Timer HIIT Timer",
        "website": "https://apps.apple.com/us/app/interval-timer-hiit-timer/id1124297113",
        "description": "iOS HIIT timer. 86K ratings, 4.8★. Free + subscription ($3.99/mo or $19.99/yr). Free version 1 workout/day.",
        "platforms": {"ios": "id1124297113"},
    },
    {
        "name": "Tabata Stopwatch Pro",
        "website": "https://apps.apple.com/us/app/tabata-timer-and-hiit-timer/id664563975",
        "description": "iOS Tabata/HIIT timer. Free + IAP. Apple Health integration. Voice assistance.",
        "platforms": {"ios": "id664563975"},
    },
]

count = 0
for comp in COMPETITORS:
    cid = db.add_competitor(
        name=comp["name"],
        website=comp.get("website"),
        description=comp.get("description"),
    )
    if cid:
        count += 1
        print(f"  Added: {comp['name']} (id={cid})")
    else:
        print(f"  Already exists: {comp['name']}")

print(f"\nTotal competitors added: {count}")
