// 小语种检查 - 本地 OCR 引擎（Apple Vision + NaturalLanguage）
// 用法：
//   lang_ocr --serve                      从 stdin 逐行读取 JSON 请求，逐行输出 JSON 结果
//   lang_ocr [--level N] [--mode M] 文件…   命令行直接识别，输出 JSON
import Foundation
import Vision
import ImageIO
import NaturalLanguage
import CoreGraphics

setvbuf(stdout, nil, _IOLBF, 0)

// MARK: - 数据结构

struct Obs {
    var text: String
    var conf: Float
    var box: CGRect      // 归一化坐标，左上角原点
    var pass: String
    var group: String
}

struct Options {
    var level = 1               // 0 全图 / 1 +2x2 / 2 +3x3 / 3 +4x4
    var groups = ["auto", "cyrillic"]
    var maxPages = 20
    var minTextHeight: Float = 0.0
    var langCorrection = false
    var full = true
    var grids: [Int]? = nil
}

let latinLangs = ["en-US", "fr-FR", "de-DE", "es-ES", "it-IT", "pt-BR", "nl-NL", "sv-SE", "da-DK",
                  "nb-NO", "pl-PL", "cs-CZ", "ro-RO", "tr-TR", "id-ID", "ms-MY", "vi-VT"]
let groupLangs: [String: [String]] = [
    "auto": [],
    "latin": latinLangs,
    "cyrillic": ["ru-RU", "uk-UA"],
    "thai": ["th-TH"],
    "arabic": ["ar-SA", "ars-SA"],
    "vietnamese": ["vi-VT"],
    "cjk": ["zh-Hans", "zh-Hant", "ja-JP", "ko-KR", "en-US"],
]

// MARK: - 图片加载

func loadImages(path: String, maxPages: Int) -> [(CGImage, String)] {
    let url = URL(fileURLWithPath: path)
    let ext = url.pathExtension.lowercased()
    if ext == "pdf" {
        guard let doc = CGPDFDocument(url as CFURL) else { return [] }
        var out: [(CGImage, String)] = []
        let n = min(doc.numberOfPages, maxPages)
        if n < 1 { return [] }
        for i in 1...n {
            guard let page = doc.page(at: i) else { continue }
            let rect = page.getBoxRect(.mediaBox)
            let longSide = max(rect.width, rect.height)
            if longSide <= 0 { continue }
            let scale = 3000.0 / longSide
            let w = Int(rect.width * scale), h = Int(rect.height * scale)
            guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                                      space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { continue }
            ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
            ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
            ctx.scaleBy(x: scale, y: scale)
            ctx.drawPDFPage(page)
            if let img = ctx.makeImage() { out.append((img, "p\(i)")) }
        }
        return out
    }
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil) else { return [] }
    let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any]
    let pw = (props?[kCGImagePropertyPixelWidth] as? Int) ?? 0
    let ph = (props?[kCGImagePropertyPixelHeight] as? Int) ?? 0
    let maxSide = max(pw, ph, 1)
    let opts: [CFString: Any] = [
        kCGImageSourceCreateThumbnailFromImageAlways: true,
        kCGImageSourceCreateThumbnailWithTransform: true,
        kCGImageSourceThumbnailMaxPixelSize: min(maxSide, 12000),
    ]
    if let img = CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary) {
        return [(img, "")]
    }
    if let img = CGImageSourceCreateImageAtIndex(src, 0, nil) { return [(img, "")] }
    return []
}

func upscaled(_ img: CGImage, minLong: Int) -> CGImage {
    let long = max(img.width, img.height)
    if long >= minLong { return img }
    let s = Double(minLong) / Double(long)
    let w = Int(Double(img.width) * s), h = Int(Double(img.height) * s)
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return img }
    ctx.interpolationQuality = .high
    ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
    return ctx.makeImage() ?? img
}

// MARK: - 识别

func recognize(_ img: CGImage, group: String, opt: Options) -> [(String, Float, CGRect)] {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = opt.langCorrection
    req.minimumTextHeight = opt.minTextHeight
    let langs = groupLangs[group] ?? []
    if langs.isEmpty {
        req.automaticallyDetectsLanguage = true
    } else {
        req.recognitionLanguages = langs
        req.automaticallyDetectsLanguage = false
    }
    let handler = VNImageRequestHandler(cgImage: img, options: [:])
    do { try handler.perform([req]) } catch { return [] }
    var out: [(String, Float, CGRect)] = []
    for o in req.results ?? [] {
        guard let c = o.topCandidates(1).first else { continue }
        let t = c.string.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty { continue }
        let b = o.boundingBox
        out.append((t, c.confidence, CGRect(x: b.minX, y: 1 - b.maxY, width: b.width, height: b.height)))
    }
    return out
}

func tiles(level: Int, only: [Int]? = nil) -> [(String, CGRect)] {
    var grids: [Int] = only ?? []
    if only == nil {
    if level >= 1 { grids.append(2) }
    if level >= 2 { grids.append(3) }
    if level >= 3 { grids.append(4) }
    }
    var out: [(String, CGRect)] = []
    for g in grids {
        let step = 1.0 / Double(g)
        let ov = step * 0.18
        for r in 0..<g {
            for c in 0..<g {
                let x0 = max(0, Double(c) * step - ov), y0 = max(0, Double(r) * step - ov)
                let x1 = min(1, Double(c + 1) * step + ov), y1 = min(1, Double(r + 1) * step + ov)
                out.append(("\(g)x\(g)-\(r)\(c)", CGRect(x: x0, y: y0, width: x1 - x0, height: y1 - y0)))
            }
        }
    }
    return out
}

func iou(_ a: CGRect, _ b: CGRect) -> Double {
    let i = a.intersection(b)
    if i.isNull || i.isEmpty { return 0 }
    let ia = Double(i.width * i.height)
    return ia / Double(a.width * a.height + b.width * b.height - i.width * i.height)
}

func overlapSmall(_ a: CGRect, _ b: CGRect) -> Double {
    let i = a.intersection(b)
    if i.isNull || i.isEmpty { return 0 }
    return Double(i.width * i.height) / Double(min(a.width * a.height, b.width * b.height))
}

func norm(_ s: String) -> String {
    s.lowercased().filter { $0.isLetter || $0.isNumber }
}

func dedup(_ all: [Obs]) -> [Obs] {
    let sorted = all.sorted { ($0.conf * Float(min($0.text.count, 40))) > ($1.conf * Float(min($1.text.count, 40))) }
    var kept: [Obs] = []
    for o in sorted {
        let n = norm(o.text)
        var dup = false
        for k in kept {
            let kn = norm(k.text)
            if iou(o.box, k.box) > 0.45 || (overlapSmall(o.box, k.box) > 0.7 && (kn.contains(n) || n.contains(kn))) {
                if o.group == k.group || kn == n || kn.contains(n) { dup = true; break }
            }
        }
        if !dup { kept.append(o) }
    }
    return kept.sorted { ($0.box.minY, $0.box.minX) < ($1.box.minY, $1.box.minX) }
}

func nlHypotheses(_ text: String, n: Int = 3) -> [[String: Any]] {
    let r = NLLanguageRecognizer()
    r.processString(text)
    return r.languageHypotheses(withMaximum: n)
        .sorted { $0.value > $1.value }
        .map { ["lang": $0.key.rawValue, "p": (($0.value * 1000).rounded() / 1000)] }
}

func process(path: String, opt: Options) -> [String: Any] {
    let t0 = Date()
    let url0 = URL(fileURLWithPath: path)
    if url0.pathExtension.lowercased() != "pdf", let src0 = CGImageSourceCreateWithURL(url0 as CFURL, nil) {
        let st = CGImageSourceGetStatusAtIndex(src0, 0)
        if st == .statusIncomplete || st == .statusReadingHeader || st == .statusUnknownType || st == .statusInvalidData {
            return ["path": path, "error": "图片不完整或数据损坏（可能下载/拷贝时被截断）", "incomplete": true]
        }
    }
    let imgs = loadImages(path: path, maxPages: opt.maxPages)
    if imgs.isEmpty { return ["path": path, "error": "无法读取图片"] }
    var pagesOut: [[String: Any]] = []
    for (img, tag) in imgs {
        var all: [Obs] = []
        for g in (opt.full ? opt.groups : []) {
            for (t, c, b) in recognize(img, group: g, opt: opt) {
                all.append(Obs(text: t, conf: c, box: b, pass: "full", group: g))
            }
        }
        let W = Double(img.width), H = Double(img.height)
        for (name, r) in tiles(level: opt.level, only: opt.grids) {
            let px = CGRect(x: r.minX * W, y: r.minY * H, width: r.width * W, height: r.height * H).integral
            guard let crop = img.cropping(to: px) else { continue }
            let up = upscaled(crop, minLong: 1800)
            for g in opt.groups {
                for (t, c, b) in recognize(up, group: g, opt: opt) {
                    let gb = CGRect(x: (px.minX + b.minX * px.width) / W, y: (px.minY + b.minY * px.height) / H,
                                    width: b.width * px.width / W, height: b.height * px.height / H)
                    all.append(Obs(text: t, conf: c, box: gb, pass: name, group: g))
                }
            }
        }
        let kept = dedup(all)
        let items: [[String: Any]] = kept.map { o in
            [
                "text": o.text,
                "conf": (Double(o.conf) * 100).rounded() / 100,
                "box": [o.box.minX, o.box.minY, o.box.width, o.box.height].map { (Double($0) * 10000).rounded() / 10000 },
                "pass": o.pass,
                "group": o.group,
                "nl": nlHypotheses(o.text),
            ]
        }
        pagesOut.append(["page": tag, "width": img.width, "height": img.height, "items": items])
    }
    return ["path": path, "pages": pagesOut, "ms": Int(Date().timeIntervalSince(t0) * 1000)]
}

func emit(_ obj: [String: Any]) {
    if let d = try? JSONSerialization.data(withJSONObject: obj, options: []), let s = String(data: d, encoding: .utf8) {
        print(s)
    }
}

// MARK: - 入口

var args = Array(CommandLine.arguments.dropFirst())
var opt = Options()
var files: [String] = []
var serve = false
var i = 0
while i < args.count {
    let a = args[i]
    switch a {
    case "--serve": serve = true
    case "--level": i += 1; opt.level = Int(args[i]) ?? 1
    case "--groups": i += 1; opt.groups = args[i].split(separator: ",").map(String.init)
    case "--mth": i += 1; opt.minTextHeight = Float(args[i]) ?? 0
    case "--lc": opt.langCorrection = true
    default: files.append(a)
    }
    i += 1
}

if serve {
    emit(["ready": true, "languages": (try? VNRecognizeTextRequest().supportedRecognitionLanguages()) ?? []])
    while let line = readLine() {
        guard let d = line.data(using: .utf8),
              let req = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let path = req["path"] as? String else {
            emit(["error": "bad request"]); continue
        }
        var o = opt
        if let l = req["level"] as? Int { o.level = l }
        if let g = req["groups"] as? [String], !g.isEmpty { o.groups = g }
        if let m = req["maxPages"] as? Int { o.maxPages = m }
        if let f = req["full"] as? Bool { o.full = f }
        if let gs = req["grids"] as? [Int] { o.grids = gs }
        var res = autoreleasepool { process(path: path, opt: o) }
        res["id"] = req["id"] ?? ""
        emit(res)
    }
} else {
    for f in files { emit(process(path: f, opt: opt)) }
}
