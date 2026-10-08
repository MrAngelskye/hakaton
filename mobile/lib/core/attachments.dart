import 'dart:convert';
import 'dart:io';
import 'package:path_provider/path_provider.dart';
import 'package:image_picker/image_picker.dart';
import 'package:uuid/uuid.dart';
import 'api.dart';
import 'models.dart';

class DraftPhotos {
  final String identity, kind;
  final int id;
  DraftPhotos(this.identity, this.kind, this.id);
  Future<Directory> get directory async => Directory(
    '${(await getApplicationSupportDirectory()).path}/drafts/${fingerprint(identity)}/$kind/$id',
  );
  Future<String> keep(XFile image) async {
    final extension = image.name.split('.').last.toLowerCase();
    if (!['jpg', 'jpeg', 'png', 'webp'].contains(extension)) {
      throw const ApiException('Выберите фото JPG, PNG или WebP.');
    }
    if (await image.length() > 8 * 1024 * 1024) {
      throw const ApiException(
        'Фотография больше 8 МБ. Выберите снимок меньшего размера.',
      );
    }
    final folder = await directory;
    await folder.create(recursive: true);
    final path = '${folder.path}/${const Uuid().v4()}.$extension';
    await image.saveTo(path);
    return path;
  }

  Future<List<Json>> upload(List<String> paths) async {
    final folder = await directory;
    final result = <Json>[];
    for (final path in paths) {
      if (!path.startsWith('${folder.path}/') || path.contains('..')) {
        throw const ApiException(
          'Неверный путь к фотографии. Добавьте снимок заново.',
        );
      }
      final file = File(path);
      if (!await file.exists()) {
        throw const ApiException(
          'Снимок из черновика недоступен. Добавьте его заново.',
        );
      }
      if (await file.length() > 8 * 1024 * 1024) {
        throw const ApiException('Фото больше 8 МБ.');
      }
      result.add({
        'name': path.split('/').last,
        'content': base64Encode(await file.readAsBytes()),
      });
    }
    return result;
  }

  Future<void> remove(String path) async {
    final folder = await directory;
    if (path.startsWith('${folder.path}/') && !path.contains('..')) {
      final file = File(path);
      if (await file.exists()) await file.delete();
    }
  }
}
