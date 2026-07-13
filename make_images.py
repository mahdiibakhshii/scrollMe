import os
from PIL import Image, ImageDraw, ImageFont

def create_placeholder_images():
    os.makedirs('static/images', exist_ok=True)
    
    # Colors for different tension levels
    colors = [
        (40, 167, 69),   # 0% - Green
        (255, 193, 7),   # 25% - Yellow
        (253, 126, 20),  # 50% - Orange
        (220, 53, 69),   # 75% - Red
        (0, 0, 0)        # 100% - Black
    ]
    
    labels = ["0%", "25%", "50%", "75%", "100%"]
    
    for i in range(5):
        img_size = (1080, 1920)
        img = Image.new('RGB', img_size, color=colors[i])
        
        # We can just leave them as colored backgrounds
        # Let's add some text just so it's obvious if possible
        draw = ImageDraw.Draw(img)
        text = f"Image {i+1} - Tension {labels[i]}"
        # Very simple drawing
        draw.text((100, 960), text, fill=(255,255,255), align="center")
        
        img.save(f'static/images/tension_{i}.jpg')
        print(f"Created static/images/{i}.jpg")

if __name__ == '__main__':
    create_placeholder_images()
