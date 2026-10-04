import base64,tempfile,unittest,sys
from pathlib import Path
from io import BytesIO
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.photo_pipeline import encode_photo

class PhotoPipelineTests(unittest.TestCase):
    def test_camera_size_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            image=Image.new('RGB',(4000,3000),'blue');exif=Image.Exif();exif[36867]='2026:10:04 10:00:00';exif[270]='private device description'
            p=Path(folder)/'camera.jpg';image.save(p,'JPEG',exif=exif)
            encoded=encode_photo(p);raw=base64.b64decode(encoded['content'])
            with Image.open(BytesIO(raw)) as prepared:
                self.assertLessEqual(max(prepared.size),1600);self.assertEqual(prepared.getexif()[36867],'2026:10:04 10:00:00');self.assertNotIn(270,prepared.getexif());self.assertLess(len(raw),p.stat().st_size)

if __name__=='__main__':unittest.main()
