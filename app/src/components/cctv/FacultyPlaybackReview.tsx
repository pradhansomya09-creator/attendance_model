import { useCallback, useEffect, useRef, useState } from "react"
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  Clock,
  Download,
  Film,
  HardDrive,
  History,
  Maximize2,
  Pause,
  Play,
  RotateCcw,
  RotateCw,
  Search,
  Shield,
  ShieldCheck,
  Trash2,
  UserCheck,
  UserX,
  Volume2,
  VolumeX,
  X,
} from "lucide-react"
import { recordingService } from "@/services/recordingService"
import type {
  AuditTrailResponse,
  ClassSessionRecordingItem,
  RecordingRosterResponse,
  RetentionPolicyStats,
  StudentSessionRosterItem,
} from "@/types/recordings"

export function FacultyPlaybackReview() {
  const [recordings, setRecordings] = useState<ClassSessionRecordingItem[]>([])
  const [selectedRecordingId, setSelectedRecordingId] = useState<string>("")
  const [activeRecording, setActiveRecording] = useState<ClassSessionRecordingItem | null>(null)
  const [rosterData, setRosterData] = useState<RecordingRosterResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [facultyName, setFacultyName] = useState("Dr. Sarah Jenkins (Faculty)")

  // Filters
  const [filterCourse, setFilterCourse] = useState<string>("")
  const [filterSection, setFilterSection] = useState<string>("")
  const [filterDate, setFilterDate] = useState<string>(() =>
    new Date().toISOString().slice(0, 10),
  )

  // Video player state
  const videoRef = useRef<HTMLVideoElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playbackRate, setPlaybackRate] = useState(1.0)
  const [isMuted, setIsMuted] = useState(false)

  // Attendance correction modal
  const [correctingStudent, setCorrectingStudent] = useState<StudentSessionRosterItem | null>(null)
  const [targetStatus, setTargetStatus] = useState<"present" | "late" | "absent">("present")
  const [correctionReason, setCorrectionReason] = useState("")
  const [submittingCorrection, setSubmittingCorrection] = useState(false)

  // Audit trail modal
  const [showAuditModal, setShowAuditModal] = useState(false)
  const [auditData, setAuditData] = useState<AuditTrailResponse | null>(null)
  const [loadingAudit, setLoadingAudit] = useState(false)

  // Retention modal
  const [showRetentionModal, setShowRetentionModal] = useState(false)
  const [retentionStats, setRetentionStats] = useState<RetentionPolicyStats | null>(null)
  const [newRetentionDays, setNewRetentionDays] = useState(30)
  const [savingRetention, setSavingRetention] = useState(false)

  // Toast / notification
  const [toastMessage, setToastMessage] = useState<string | null>(null)

  // 1. Load available recordings matching filters
  const loadRecordings = useCallback(async () => {
    setLoading(true)
    try {
      const list = await recordingService.listRecordings({
        course: filterCourse || undefined,
        section: filterSection || undefined,
        date: filterDate || undefined,
      })
      setRecordings(list)
      if (list.length > 0) {
        const targetId =
          selectedRecordingId && list.some((r) => r.id === selectedRecordingId)
            ? selectedRecordingId
            : list[0].id
        setSelectedRecordingId(targetId)
        setActiveRecording(list.find((r) => r.id === targetId) ?? list[0])
      } else {
        setSelectedRecordingId("")
        setActiveRecording(null)
        setRosterData(null)
      }
    } catch (err) {
      setToastMessage(err instanceof Error ? err.message : "Failed to load class recordings")
    } finally {
      setLoading(false)
    }
  }, [filterCourse, filterDate, filterSection, selectedRecordingId])

  useEffect(() => {
    void loadRecordings()
  }, [loadRecordings])

  // 2. Load roster and detection events when selected recording changes
  useEffect(() => {
    if (!selectedRecordingId) return
    let cancelled = false
    const loadRoster = async () => {
      try {
        const res = await recordingService.getRoster(selectedRecordingId)
        if (!cancelled) {
          setRosterData(res)
        }
      } catch (err) {
        if (!cancelled) {
          console.warn("Could not load recording roster:", err)
        }
      }
    }
    void loadRoster()
    return () => {
      cancelled = true
    }
  }, [selectedRecordingId])

  // Video player control callbacks
  const togglePlay = () => {
    if (!videoRef.current) return
    if (isPlaying) {
      videoRef.current.pause()
      setIsPlaying(false)
    } else {
      void videoRef.current.play()
      setIsPlaying(true)
    }
  }

  const handleSeek = (newTime: number) => {
    if (!videoRef.current) return
    videoRef.current.currentTime = newTime
    setCurrentTime(newTime)
  }

  const skipSeconds = (delta: number) => {
    if (!videoRef.current) return
    handleSeek(Math.max(0, Math.min(duration, currentTime + delta)))
  }

  const handleSpeedChange = (rate: number) => {
    if (!videoRef.current) return
    videoRef.current.playbackRate = rate
    setPlaybackRate(rate)
  }

  const jumpToStudentDetection = (timestampSeconds: number) => {
    handleSeek(timestampSeconds)
    if (videoRef.current && !isPlaying) {
      void videoRef.current.play()
      setIsPlaying(true)
    }
    setToastMessage(`Jumped to student detection at ${formatTime(timestampSeconds)}`)
  }

  // Submit attendance correction
  const handleOpenCorrection = (
    student: StudentSessionRosterItem,
    statusOption: "present" | "late" | "absent",
  ) => {
    setCorrectingStudent(student)
    setTargetStatus(statusOption)
    setCorrectionReason(`Verified via video playback review at ${formatTime(currentTime)}`)
  }

  const handleSaveCorrection = async () => {
    if (!correctingStudent || !selectedRecordingId || correctionReason.trim().length < 3) return
    setSubmittingCorrection(true)
    try {
      const res = await recordingService.submitAttendanceCorrection(selectedRecordingId, {
        member_id: correctingStudent.member_id,
        new_status: targetStatus,
        reason: correctionReason.trim(),
        corrected_by: facultyName,
      })
      setToastMessage(
        `Attendance updated: ${res.student_name} marked ${res.new_status.toUpperCase()}`,
      )
      setCorrectingStudent(null)
      // Reload roster
      const updated = await recordingService.getRoster(selectedRecordingId)
      setRosterData(updated)
    } catch (err) {
      setToastMessage(err instanceof Error ? err.message : "Failed to record correction")
    } finally {
      setSubmittingCorrection(false)
    }
  }

  // Load audit trail
  const handleOpenAudit = async () => {
    if (!selectedRecordingId) return
    setShowAuditModal(true)
    setLoadingAudit(true)
    try {
      const data = await recordingService.getAuditTrail(selectedRecordingId)
      setAuditData(data)
    } catch (err) {
      setToastMessage("Failed to load audit history")
    } finally {
      setLoadingAudit(false)
    }
  }

  // Load retention settings
  const handleOpenRetention = async () => {
    setShowRetentionModal(true)
    try {
      const stats = await recordingService.getRetentionSettings()
      setRetentionStats(stats)
      setNewRetentionDays(stats.default_retention_days)
    } catch {
      setToastMessage("Failed to load retention settings")
    }
  }

  const handleSaveRetention = async () => {
    setSavingRetention(true)
    try {
      const res = await recordingService.updateRetentionPolicy(newRetentionDays)
      setToastMessage(
        `Retention set to ${res.new_retention_days} days. ${res.pruned_recordings_count} expired recordings pruned.`,
      )
      setShowRetentionModal(false)
      void loadRecordings()
    } catch (err) {
      setToastMessage(err instanceof Error ? err.message : "Failed to update retention policy")
    } finally {
      setSavingRetention(false)
    }
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-[#0a0c10] text-white">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed top-4 right-4 z-50 flex items-center gap-2 rounded-lg border border-cyan-500/40 bg-black/90 px-4 py-2 text-xs font-semibold text-cyan-200 shadow-2xl backdrop-blur-md animate-in fade-in">
          <ShieldCheck className="size-4 text-cyan-400" />
          <span>{toastMessage}</span>
          <button
            type="button"
            onClick={() => setToastMessage(null)}
            className="ml-2 text-white/50 hover:text-white">
            <X className="size-3.5" />
          </button>
        </div>
      )}

      {/* 1. Header Filter Bar (Course, Section, Date, Session) */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 bg-[#0f121a] px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="flex items-center gap-2 rounded-lg border border-cyan-500/30 bg-cyan-950/30 px-3 py-1.5 text-xs font-bold text-cyan-300">
            <Film className="size-4 text-cyan-400" />
            <span>Class Video Playback & Attendance Review</span>
          </div>

          {/* Filter: Course */}
          <div className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-black/50 px-2.5 py-1 text-xs">
            <span className="text-white/40">Course:</span>
            <select
              value={filterCourse}
              onChange={(e) => setFilterCourse(e.target.value)}
              className="bg-transparent font-medium text-white focus:outline-none">
              <option value="" className="bg-[#11141d]">All Courses</option>
              <option value="CS-301" className="bg-[#11141d]">CS-301: AI & Vision</option>
              <option value="CS-204" className="bg-[#11141d]">CS-204: Data Structures</option>
              <option value="EC-401" className="bg-[#11141d]">EC-401: Embedded Systems</option>
            </select>
          </div>

          {/* Filter: Section */}
          <div className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-black/50 px-2.5 py-1 text-xs">
            <span className="text-white/40">Section:</span>
            <select
              value={filterSection}
              onChange={(e) => setFilterSection(e.target.value)}
              className="bg-transparent font-medium text-white focus:outline-none">
              <option value="" className="bg-[#11141d]">All Sections</option>
              <option value="Section A" className="bg-[#11141d]">Section A</option>
              <option value="Section B" className="bg-[#11141d]">Section B</option>
              <option value="Section C" className="bg-[#11141d]">Section C</option>
            </select>
          </div>

          {/* Filter: Date */}
          <div className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-black/50 px-2.5 py-1 text-xs">
            <Calendar className="size-3 text-cyan-400" />
            <input
              type="date"
              value={filterDate}
              onChange={(e) => setFilterDate(e.target.value)}
              className="bg-transparent font-medium text-white focus:outline-none"
            />
          </div>

          {/* Session Picker */}
          {recordings.length > 0 && (
            <div className="flex items-center gap-1.5 rounded-lg border border-white/15 bg-black/60 px-2.5 py-1 text-xs">
              <Clock className="size-3 text-emerald-400" />
              <select
                value={selectedRecordingId}
                onChange={(e) => {
                  setSelectedRecordingId(e.target.value)
                  setActiveRecording(recordings.find((r) => r.id === e.target.value) ?? null)
                }}
                className="bg-transparent font-semibold text-cyan-200 focus:outline-none">
                {recordings.map((r) => (
                  <option key={r.id} value={r.id} className="bg-[#11141d]">
                    {r.course_code} {r.section} • {r.start_time}-{r.end_time} ({r.classroom || "Room"})
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Right Action Tools: Audit Trail & Retention */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleOpenAudit}
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1 text-xs font-medium text-white/80 transition hover:bg-white/10 hover:text-white">
            <History className="size-3.5 text-cyan-400" />
            <span>Audit Trail</span>
          </button>
          <button
            type="button"
            onClick={handleOpenRetention}
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1 text-xs font-medium text-white/80 transition hover:bg-white/10 hover:text-white">
            <HardDrive className="size-3.5 text-amber-400" />
            <span>Retention & Storage</span>
          </button>
        </div>
      </div>

      {/* 2. Main Content Split View: Stored Video Player (Left) + Student Attendance Review (Right) */}
      <div className="flex min-h-0 flex-1 flex-col gap-3 p-3 lg:flex-row">
        {/* Left Column: Video Player & Timeline Scrubber */}
        <div className="flex flex-1 flex-col overflow-hidden rounded-xl border border-white/10 bg-[#0d1017]">
          {activeRecording ? (
            <div className="flex h-full w-full flex-col">
              {/* Video Viewport */}
              <div className="relative flex min-h-[280px] flex-1 items-center justify-center bg-black">
                <video
                  ref={videoRef}
                  src={recordingService.getStreamUrl(activeRecording.id, facultyName)}
                  className="h-full w-full object-contain"
                  onTimeUpdate={() => {
                    if (videoRef.current) setCurrentTime(videoRef.current.currentTime)
                  }}
                  onLoadedMetadata={() => {
                    if (videoRef.current) setDuration(videoRef.current.duration || 60)
                  }}
                  onEnded={() => setIsPlaying(false)}
                  playsInline
                />

                {/* Floating Top Info Overlay */}
                <div className="pointer-events-none absolute top-3 left-3 flex items-center gap-2 rounded-full border border-white/15 bg-black/75 px-3 py-1 text-xs backdrop-blur-md">
                  <span className="size-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
                  <span className="font-semibold">{activeRecording.course_code} - {activeRecording.section}</span>
                  <span className="text-white/40">•</span>
                  <span className="text-white/70">{activeRecording.session_date} ({activeRecording.start_time} - {activeRecording.end_time})</span>
                </div>
              </div>

              {/* Video Timeline Scrubber with Detection Bookmarks */}
              <div className="border-t border-white/10 bg-[#121620] px-4 py-2.5">
                {/* Timeline Bar with Event Pins */}
                <div className="relative mb-2 flex items-center">
                  <input
                    type="range"
                    min={0}
                    max={duration || 100}
                    step={0.1}
                    value={currentTime}
                    onChange={(e) => handleSeek(Number(e.target.value))}
                    className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-white/20 accent-cyan-400"
                  />

                  {/* Detection Bookmark Pins */}
                  {(rosterData?.roster ?? []).map((student) => {
                    if (!duration || student.video_timestamp_seconds > duration) return null
                    const leftPct = (student.video_timestamp_seconds / duration) * 100
                    return (
                      <button
                        key={`pin-${student.member_id}`}
                        type="button"
                        onClick={() => jumpToStudentDetection(student.video_timestamp_seconds)}
                        title={`${student.name} detected at ${student.video_timestamp_formatted}`}
                        style={{ left: `${leftPct}%` }}
                        className="absolute -top-1.5 size-3.5 -translate-x-1/2 rounded-full border border-black bg-cyan-400 shadow-sm transition hover:scale-125"
                      />
                    )
                  })}
                </div>

                {/* Controls Bar */}
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={togglePlay}
                      className="rounded-lg border border-cyan-500/40 bg-cyan-500/20 p-2 text-cyan-200 transition hover:bg-cyan-500/30 hover:text-white">
                      {isPlaying ? <Pause className="size-4" /> : <Play className="size-4" />}
                    </button>
                    <button
                      type="button"
                      onClick={() => skipSeconds(-5)}
                      title="Rewind 5 seconds"
                      className="p-1.5 text-white/70 hover:text-white">
                      <RotateCcw className="size-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => skipSeconds(5)}
                      title="Forward 5 seconds"
                      className="p-1.5 text-white/70 hover:text-white">
                      <RotateCw className="size-4" />
                    </button>

                    <div className="font-mono text-xs text-white/70">
                      <span>{formatTime(currentTime)}</span>
                      <span className="text-white/40"> / </span>
                      <span>{formatTime(duration)}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    {/* Speed dropdown */}
                    <div className="flex items-center gap-1 rounded bg-black/40 px-2 py-0.5 text-[11px]">
                      <span className="text-white/40">Speed:</span>
                      <select
                        value={playbackRate}
                        onChange={(e) => handleSpeedChange(Number(e.target.value))}
                        className="bg-transparent font-medium text-cyan-300 focus:outline-none">
                        <option value={0.5} className="bg-[#11141d]">0.5x</option>
                        <option value={1.0} className="bg-[#11141d]">1.0x</option>
                        <option value={1.25} className="bg-[#11141d]">1.25x</option>
                        <option value={1.5} className="bg-[#11141d]">1.5x</option>
                        <option value={2.0} className="bg-[#11141d]">2.0x</option>
                      </select>
                    </div>

                    {/* Mute */}
                    <button
                      type="button"
                      onClick={() => {
                        if (videoRef.current) {
                          videoRef.current.muted = !isMuted
                          setIsMuted(!isMuted)
                        }
                      }}
                      className="p-1.5 text-white/70 hover:text-white">
                      {isMuted ? <VolumeX className="size-4 text-rose-400" /> : <Volume2 className="size-4" />}
                    </button>

                    {/* Fullscreen */}
                    <button
                      type="button"
                      onClick={() => {
                        if (videoRef.current) {
                          if (document.fullscreenElement) {
                            void document.exitFullscreen()
                          } else {
                            void videoRef.current.requestFullscreen()
                          }
                        }
                      }}
                      className="p-1.5 text-white/70 hover:text-white">
                      <Maximize2 className="size-4" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex h-full flex-col items-center justify-center p-6 text-center text-white/40">
              <Film className="size-10 mb-2 opacity-40 text-cyan-400" />
              <p className="text-sm font-semibold">No Recording Selected</p>
              <p className="text-xs text-white/30">Select a course, section, and date to view stored CCTV clips.</p>
            </div>
          )}
        </div>

        {/* Right Column: Attendance Review, Verification & Correction List */}
        <div className="flex w-full flex-col overflow-hidden rounded-xl border border-white/10 bg-[#0d1017] lg:w-[420px]">
          {/* Header Summary */}
          <div className="flex items-center justify-between border-b border-white/10 bg-[#121620] px-4 py-2.5">
            <div>
              <h3 className="text-xs font-bold text-white">Class Attendance Review</h3>
              <p className="text-[10px] text-white/50">
                Correct attendance based on video evidence • Changes are audited
              </p>
            </div>
            {rosterData && (
              <div className="flex items-center gap-2 text-[10.5px]">
                <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-emerald-300 font-bold">
                  {rosterData.present_count} Present
                </span>
                <span className="rounded bg-rose-500/20 px-1.5 py-0.5 text-rose-300 font-bold">
                  {rosterData.absent_count} Absent
                </span>
              </div>
            )}
          </div>

          {/* Student Roster Table */}
          <div className="flex-1 overflow-y-auto p-2">
            {(rosterData?.roster ?? []).map((student) => {
              const isPresent = student.status === "present"
              const isLate = student.status === "late"
              const isAbsent = student.status === "absent"

              return (
                <div
                  key={student.member_id}
                  className="mb-2 rounded-lg border border-white/5 bg-[#12151e] p-2.5 transition hover:border-white/15">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <div
                        className={`size-2 rounded-full ${
                          isPresent ? "bg-emerald-400" : isLate ? "bg-amber-400" : "bg-rose-500"
                        }`}
                      />
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-semibold text-white/90">{student.name}</span>
                          <span className="text-[10px] text-white/40">({student.person_id})</span>
                        </div>
                        {/* Detection Timestamp Bookmark */}
                        {student.cctv_detected && (
                          <button
                            type="button"
                            onClick={() => jumpToStudentDetection(student.video_timestamp_seconds)}
                            className="inline-flex items-center gap-1 text-[10px] text-cyan-400 hover:underline">
                            <Clock className="size-2.5" />
                            <span>Seen at {student.video_timestamp_formatted} (Jump to Clip)</span>
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Status Badge */}
                    <span
                      className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase ${
                        isPresent
                          ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                          : isLate
                            ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                            : "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                      }`}>
                      {student.status}
                    </span>
                  </div>

                  {/* Correction Actions */}
                  <div className="mt-2 flex items-center justify-between border-t border-white/5 pt-1.5 text-[11px]">
                    <span className="text-[9.5px] text-white/40 truncate max-w-[170px]" title={student.latest_reason}>
                      {student.last_modified_by}: {student.latest_reason}
                    </span>

                    <div className="flex items-center gap-1">
                      {!isPresent && (
                        <button
                          type="button"
                          onClick={() => handleOpenCorrection(student, "present")}
                          className="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300 hover:bg-emerald-500/20">
                          Present
                        </button>
                      )}
                      {!isLate && (
                        <button
                          type="button"
                          onClick={() => handleOpenCorrection(student, "late")}
                          className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-300 hover:bg-amber-500/20">
                          Late
                        </button>
                      )}
                      {!isAbsent && (
                        <button
                          type="button"
                          onClick={() => handleOpenCorrection(student, "absent")}
                          className="rounded border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 text-[10px] font-semibold text-rose-300 hover:bg-rose-500/20">
                          Absent
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* 3. Modal: Attendance Correction Reason & Author Dialog */}
      {correctingStudent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-white/20 bg-[#121622] p-4 shadow-2xl">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Shield className="size-4 text-cyan-400" />
              <span>Correct Student Attendance</span>
            </h3>
            <p className="mt-1 text-xs text-white/60">
              Updating <strong>{correctingStudent.name}</strong> to{" "}
              <span className="font-bold text-cyan-300 uppercase">{targetStatus}</span>. All modifications are logged in the immutable audit trail.
            </p>

            <div className="mt-3 flex flex-col gap-2.5">
              <div>
                <label className="text-[11px] font-semibold text-white/70">Faculty Reviewer Identity:</label>
                <input
                  type="text"
                  value={facultyName}
                  onChange={(e) => setFacultyName(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/50 px-3 py-1.5 text-xs text-white focus:border-cyan-400 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-[11px] font-semibold text-white/70">Mandatory Justification / Review Reason:</label>
                <textarea
                  rows={3}
                  value={correctionReason}
                  onChange={(e) => setCorrectionReason(e.target.value)}
                  placeholder="e.g. Verified student seated in Row 3 at video timestamp 01:15..."
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/50 px-3 py-1.5 text-xs text-white placeholder-white/30 focus:border-cyan-400 focus:outline-none"
                />
              </div>
            </div>

            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setCorrectingStudent(null)}
                className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-white/70 hover:bg-white/10">
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveCorrection}
                disabled={submittingCorrection || correctionReason.trim().length < 3}
                className="rounded-lg border border-cyan-500/40 bg-cyan-500/30 px-3 py-1.5 text-xs font-bold text-white transition hover:bg-cyan-500/40 disabled:opacity-40">
                {submittingCorrection ? "Recording Audit..." : "Confirm & Log Correction"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 4. Modal: Audit Trail Drawer */}
      {showAuditModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="flex h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-white/20 bg-[#121622] p-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 pb-2">
              <div>
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <History className="size-4 text-cyan-400" />
                  <span>Audit Trail • Video Access & Attendance Edits</span>
                </h3>
                <p className="text-[11px] text-white/50">{auditData?.course} ({auditData?.session_date})</p>
              </div>
              <button
                type="button"
                onClick={() => setShowAuditModal(false)}
                className="text-white/60 hover:text-white">
                <X className="size-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto pt-3">
              <h4 className="text-xs font-bold text-cyan-300 uppercase mb-2">Attendance Modifications</h4>
              {(auditData?.attendance_corrections ?? []).length === 0 ? (
                <p className="text-xs text-white/40 italic">No manual corrections logged yet.</p>
              ) : (
                <div className="space-y-2 mb-4">
                  {auditData?.attendance_corrections.map((c) => (
                    <div key={c.id} className="rounded border border-white/10 bg-black/40 p-2.5 text-xs">
                      <div className="flex items-center justify-between font-semibold">
                        <span className="text-white">{c.student_name}</span>
                        <span className="text-cyan-400 uppercase">{c.previous_status} ➔ {c.new_status}</span>
                      </div>
                      <p className="text-white/70 mt-1">Reason: "{c.reason}"</p>
                      <p className="text-[10px] text-white/40 mt-1">By: {c.corrected_by} • {new Date(c.timestamp).toLocaleString()}</p>
                    </div>
                  ))}
                </div>
              )}

              <h4 className="text-xs font-bold text-amber-300 uppercase mb-2">Video Access Logs</h4>
              <div className="space-y-1.5">
                {(auditData?.video_access_logs ?? []).map((v) => (
                  <div key={v.id} className="flex items-center justify-between rounded bg-white/5 px-2.5 py-1 text-[11px]">
                    <span className="text-white/80">{v.accessed_by}</span>
                    <span className="text-white/50">{v.access_type} ({v.ip_address || "LAN"})</span>
                    <span className="text-white/40 text-[10px]">{new Date(v.timestamp).toLocaleTimeString()}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 5. Modal: Retention & Storage Governance */}
      {showRetentionModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-white/20 bg-[#121622] p-4 shadow-2xl">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <HardDrive className="size-4 text-amber-400" />
              <span>Recording Retention & Deletion Governance</span>
            </h3>
            <p className="mt-1 text-xs text-white/60">
              Configure automated clip expiration and storage controls.
            </p>

            {retentionStats && (
              <div className="mt-3 rounded-lg border border-white/10 bg-black/40 p-3 text-xs space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-white/50">Storage Used:</span>
                  <span className="font-semibold text-white">{retentionStats.storage_used_mb} MB ({retentionStats.active_recordings_count} clips)</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-white/50">Current Retention:</span>
                  <span className="font-semibold text-cyan-300">{retentionStats.default_retention_days} Days</span>
                </div>
              </div>
            )}

            <div className="mt-4">
              <label className="text-xs font-semibold text-white">Configurable Retention Period (Days):</label>
              <input
                type="number"
                min={1}
                max={365}
                value={newRetentionDays}
                onChange={(e) => setNewRetentionDays(Number(e.target.value))}
                className="mt-1.5 w-full rounded-lg border border-white/10 bg-black/50 px-3 py-1.5 text-xs text-white focus:border-cyan-400 focus:outline-none"
              />
              <p className="text-[10px] text-white/40 mt-1">Clips older than this threshold are purged safely during automatic nightly runs.</p>
            </div>

            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowRetentionModal(false)}
                className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-white/70 hover:bg-white/10">
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveRetention}
                disabled={savingRetention}
                className="rounded-lg border border-amber-500/40 bg-amber-500/30 px-3 py-1.5 text-xs font-bold text-white transition hover:bg-amber-500/40">
                {savingRetention ? "Updating..." : "Save Retention Policy"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

