package kz.bytex.naryadai_mobile

import android.Manifest
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.RecognitionListener
import org.vosk.android.SpeechService
import org.vosk.android.StorageService

class MainActivity : FlutterActivity(), RecognitionListener {
    private var sink: EventChannel.EventSink? = null
    private var model: Model? = null
    private var speech: SpeechService? = null
    private var pending: MethodChannel.Result? = null
    private var generation = 0
    private val main = Handler(Looper.getMainLooper())
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        EventChannel(flutterEngine.dartExecutor.binaryMessenger, "kz.bytex.naryadai/voice.events")
            .setStreamHandler(object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink) { sink = events }
                override fun onCancel(arguments: Any?) { stopVoice();sink = null }
            })
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "kz.bytex.naryadai/voice")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "start" -> {
                        if (speech != null || pending != null) result.error("busy", "Запись уже запускается.", null)
                        else {
                            pending = result
                            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
                                requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 4901)
                            else startVoice()
                        }
                    }
                    "stop" -> {stopVoice();main.postDelayed({ result.success(null) }, 150)}
                    else -> result.notImplemented()
                }
            }
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != 4901 || pending == null) return
        if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) startVoice()
        else {pending?.error("permission", "Доступ к микрофону запрещён. Разрешите его в настройках приложения или введите текст вручную.", null);pending = null}
    }
    private fun startVoice() {
        val ticket = ++generation
        if (model != null) beginRecognition(ticket)
        else StorageService.unpack(this, "model-ru", "voice-model", { loaded ->
            if (isDestroyed || ticket != generation) loaded.close()
            else {model = loaded;beginRecognition(ticket)}
        }, { _ -> if (ticket == generation) failure("Не удалось открыть локальную модель. Переустановите полную APK или введите текст вручную.") })
    }
    private fun beginRecognition(ticket: Int) {
        if (ticket != generation || pending == null) return
        try {
            speech = SpeechService(Recognizer(model, 16000.0f), 16000.0f)
            if (speech?.startListening(this) != true) throw IllegalStateException("microphone busy")
            emit("ready", "")
            pending?.success(null);pending = null
        } catch (_: Exception) {failure("Микрофон недоступен. Закройте другую запись и повторите попытку.")}
    }
    private fun emit(kind: String, text: String) {val target = sink;main.post {if (sink === target) target?.success(mapOf("kind" to kind, "text" to text))}}
    private fun failure(message: String) {
        pending?.error("voice", message, null);pending = null
        stopVoice();emit("error", message)
    }
    private fun stopVoice() {
        generation++
        val previous = speech;speech = null
        previous?.stop();previous?.shutdown()
        pending?.success(null);pending = null
        emit("stopped", "Запись остановлена. Проверьте текст.")
    }
    override fun onPartialResult(hypothesis: String) {emit("partial", JSONObject(hypothesis).optString("partial"))}
    override fun onResult(hypothesis: String) {emit("text", JSONObject(hypothesis).optString("text"))}
    override fun onFinalResult(hypothesis: String) {emit("text", JSONObject(hypothesis).optString("text"))}
    override fun onError(exception: Exception) {failure("Запись прервана. Проверьте микрофон и повторите попытку.")}
    override fun onTimeout() {stopVoice()}
    override fun onStop() {stopVoice();super.onStop()}
    override fun onDestroy() {stopVoice();model?.close();model = null;super.onDestroy()}
}
