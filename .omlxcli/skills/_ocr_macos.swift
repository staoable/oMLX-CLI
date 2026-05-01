// macOS Vision OCR 命令行工具
//
// 用法:
//   swift _ocr_macos.swift <image_path> [lang ...]
//
// 默认语言: zh-Hans, en-US（中英文混排自动识别）。
// 输出: stdout 输出每条识别文本（按 Vision 自然顺序），换行分隔。
// 错误: stderr，exit code 非 0。
//
// 这个脚本被 `pdf_read` / `pdf_ocr` 通过 subprocess 调用；
// 不要直接修改使用者代码：本脚本是 Python 工具的成熟 OCR 后端。

import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count >= 2 else {
    FileHandle.standardError.write(Data("Usage: \(args[0]) <image> [lang...]\n".utf8))
    exit(1)
}

let path = args[1]
let langs: [String] = {
    let rest = Array(args.dropFirst(2))
    return rest.isEmpty ? ["zh-Hans", "en-US"] : rest
}()

guard let nsImage = NSImage(contentsOfFile: path) else {
    FileHandle.standardError.write(Data("Failed to load image at \(path)\n".utf8))
    exit(2)
}
guard let cgImage = nsImage.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write(Data("Failed to obtain CGImage\n".utf8))
    exit(3)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = langs
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write(Data("Vision request failed: \(error)\n".utf8))
    exit(4)
}

guard let observations = request.results else {
    exit(0)
}

var stdout = FileHandle.standardOutput
for observation in observations {
    if let candidate = observation.topCandidates(1).first {
        if let data = (candidate.string + "\n").data(using: .utf8) {
            stdout.write(data)
        }
    }
}
