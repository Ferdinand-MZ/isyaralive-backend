@router.post("/gesture/text-to-video")
def text_to_gesture(text: str, db: Session = Depends(get_db)):
    words = text.lower().split()
    results = []
    
    for word in words:
        # Cari di database approved gesture
        gesture = find_gesture_video(word, db)
        if gesture:
            results.append({
                "word": word,
                "type": "word",
                "video_url": gesture.video_path
            })
        else:
            # Fallback: eja per huruf
            for letter in word:
                results.append({
                    "word": letter.upper(),
                    "type": "letter",
                    "video_url": get_alphabet_video(letter)
                })
    
    return {"sequence": results}