import { describe, expect, it, vi } from "vitest"
import { drawOverlays } from "./overlayRenderer"
import type { DetectionResult } from "@/components/main/types"

const createMockCtx = () => {
  const strokeStyles: string[] = []
  const fillTexts: string[] = []
  let currentStroke = ""
  const ctx = {
    imageSmoothingEnabled: true,
    globalAlpha: 1,
    lineWidth: 2,
    shadowColor: "",
    shadowBlur: 0,
    shadowOffsetX: 0,
    shadowOffsetY: 0,
    lineCap: "round",
    lineJoin: "round",
    font: "",
    textAlign: "left",
    textBaseline: "middle",
    fillStyle: "",
    set strokeStyle(val: string) {
      currentStroke = val
      strokeStyles.push(val)
    },
    get strokeStyle() {
      return currentStroke
    },
    clearRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    setLineDash: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    quadraticCurveTo: vi.fn(),
    closePath: vi.fn(),
    stroke: vi.fn(),
    measureText: vi.fn((text: string) => ({ width: text.length * 7 })),
    fillText: vi.fn((text: string) => {
      fillTexts.push(text)
    }),
  }
  return { ctx, strokeStyles, fillTexts }
}

const createParams = (
  faces: DetectionResult["faces"],
  enableSpoofDetection = false,
) => {
  const { ctx, strokeStyles, fillTexts } = createMockCtx()
  const videoEl = {
    videoWidth: 640,
    videoHeight: 480,
  } as unknown as HTMLVideoElement
  const canvasEl = {
    width: 640,
    height: 480,
    style: { width: "640px", height: "480px" },
    getContext: vi.fn(() => ctx),
  } as unknown as HTMLCanvasElement

  drawOverlays({
    videoRef: { current: videoEl },
    overlayCanvasRef: { current: canvasEl },
    currentDetections: { faces, model_used: "face_detector" },
    isStreaming: true,
    currentRecognitionResults: new Map(),
    recognitionEnabled: true,
    persistentCooldowns: new Map(),
    quickSettings: {
      showTrackingBoxes: true,
      showRecognitionNames: true,
      cameraMirrored: false,
      cameraFitCover: false,
    } as never,
    enableSpoofDetection,
    getVideoRect: () =>
      ({ width: 640, height: 480, left: 0, top: 0, right: 640, bottom: 480 }) as DOMRect,
    calculateScaleFactors: () => ({ scaleX: 1, scaleY: 1, offsetX: 0, offsetY: 0 }),
  })

  return { strokeStyles, fillTexts }
}

describe("overlayRenderer", () => {
  it("draws red bounding box and UNKNOWN PERSON label for unrecognized student", () => {
    const { strokeStyles, fillTexts } = createParams([
      {
        bbox: { x: 100, y: 80, width: 140, height: 160 },
        confidence: 0.96,
        track_id: 5,
        landmarks_5: [
          [130, 130],
          [200, 130],
          [165, 165],
          [140, 200],
          [190, 200],
        ],
        recognition: {
          success: false,
          person_id: null,
          name: null,
          similarity: 0.14,
          processing_time: 0,
          error: null,
        },
      },
    ])

    expect(strokeStyles).toContain("#ef4444")
    expect(fillTexts).toContain("UNKNOWN PERSON")
  })

  it("draws red bounding box and UNKNOWN PERSON when spoof detection confirms real unknown face", () => {
    const { strokeStyles, fillTexts } = createParams(
      [
        {
          bbox: { x: 100, y: 80, width: 140, height: 160 },
          confidence: 0.96,
          track_id: 6,
          landmarks_5: [
            [130, 130],
            [200, 130],
            [165, 165],
            [140, 200],
            [190, 200],
          ],
          liveness: { is_real: true, status: "real" },
          recognition: {
            success: false,
            person_id: null,
            name: null,
            similarity: 0.18,
            processing_time: 0,
            error: null,
          },
        },
      ],
      true,
    )

    expect(strokeStyles).toContain("#ef4444")
    expect(fillTexts).toContain("UNKNOWN PERSON")
  })

  it("draws cyan bounding box and member name for recognized student", () => {
    const { strokeStyles, fillTexts } = createParams([
      {
        bbox: { x: 100, y: 80, width: 140, height: 160 },
        confidence: 0.99,
        track_id: 7,
        landmarks_5: [
          [130, 130],
          [200, 130],
          [165, 165],
          [140, 200],
          [190, 200],
        ],
        recognition: {
          success: true,
          person_id: "stu-1",
          name: "ashish",
          similarity: 0.89,
          processing_time: 0,
          error: null,
        },
      },
    ])

    expect(strokeStyles).toContain("#22d3ee")
    expect(fillTexts).toContain("ashish")
    expect(fillTexts).not.toContain("UNKNOWN PERSON")
  })
})

