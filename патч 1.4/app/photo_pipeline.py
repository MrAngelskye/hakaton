"""Prepare a camera image for upload. Keep capture time, remove GPS metadata."""
import base64
from io import BytesIO
from pathlib import Path
from PIL import Image,ImageOps

def encode_photo(source):
    path=Path(source)
    if not path.is_file() or not 0<path.stat().st_size<=8*1024*1024:raise ValueError('Фото должно быть не больше 8 МБ.')
    try:
        with Image.open(path) as image:
            if image.format not in ('JPEG','PNG','WEBP') or image.width*image.height>40000000:raise ValueError('Фото: JPG, PNG, WebP до 40 Мп.')
            old=image.getexif();exif=Image.Exif()
            for key in (36867,306):
                if key in old:exif[key]=old[key]
            image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((1600,1600))
            buffer=BytesIO();image.save(buffer,'JPEG',quality=82,optimize=True,exif=exif)
    except (OSError,Image.DecompressionBombError):raise ValueError('Не удалось прочитать фото.') from None
    return {'name':path.stem+'.jpg','content':base64.b64encode(buffer.getvalue()).decode()}
