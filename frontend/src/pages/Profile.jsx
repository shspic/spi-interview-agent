import { useCallback, useEffect, useState } from "react";

import apiClient from "../api/client";
import { getFriendlyErrorMessage } from "../utils/errorMessage";

const EMPTY_PROFILE = {
  display_name: "",
  target_direction: "",
  self_introduction: "",
  technical_skills: [],
};

const EMPTY_JOB = {
  job_title: "",
  company_name: "",
  jd_text: "",
  notes: "",
  is_active: false,
};

function Profile({ onOpenKnowledge }) {
  const [profile, setProfile] = useState(EMPTY_PROFILE);
  const [skillsText, setSkillsText] = useState("");
  const [targetJobs, setTargetJobs] = useState([]);
  const [files, setFiles] = useState([]);
  const [jobForm, setJobForm] = useState(EMPTY_JOB);
  const [editingJobId, setEditingJobId] = useState(null);
  const [showJobForm, setShowJobForm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const loadProfileData = useCallback(async () => {
    try {
      setLoading(true);
      const [profileResponse, jobsResponse, filesResponse] = await Promise.all([
        apiClient.get("/api/profile"),
        apiClient.get("/api/target-jobs"),
        apiClient.get("/api/files"),
      ]);
      const profileData = profileResponse.data.profile || EMPTY_PROFILE;

      setProfile(profileData);
      setSkillsText((profileData.technical_skills || []).join(", "));
      setTargetJobs(jobsResponse.data.jobs || []);
      setFiles(filesResponse.data.files || []);
      setMessage("");
    } catch (error) {
      console.error("load profile error:", error);
      setMessage(getFriendlyErrorMessage(error, "加载个人资料失败。"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timerId = window.setTimeout(loadProfileData, 0);

    return () => window.clearTimeout(timerId);
  }, [loadProfileData]);

  const handleProfileChange = (event) => {
    const { name, value } = event.target;
    setProfile((current) => ({ ...current, [name]: value }));
  };

  const saveProfile = async (event) => {
    event.preventDefault();
    const technicalSkills = skillsText
      .split(/[,，\n]/)
      .map((skill) => skill.trim())
      .filter(Boolean);

    try {
      setLoading(true);
      const response = await apiClient.put("/api/profile", {
        display_name: profile.display_name,
        target_direction: profile.target_direction,
        self_introduction: profile.self_introduction,
        technical_skills: technicalSkills,
      });

      setProfile(response.data);
      setSkillsText(response.data.technical_skills.join(", "));
      setMessage("基本资料已保存。");
    } catch (error) {
      console.error("save profile error:", error);
      setMessage(getFriendlyErrorMessage(error, "保存基本资料失败。"));
    } finally {
      setLoading(false);
    }
  };

  const startCreateJob = () => {
    setEditingJobId(null);
    setJobForm(EMPTY_JOB);
    setShowJobForm(true);
    setMessage("");
  };

  const startEditJob = (job) => {
    setEditingJobId(job.id);
    setJobForm({
      job_title: job.job_title,
      company_name: job.company_name,
      jd_text: job.jd_text,
      notes: job.notes,
      is_active: job.is_active,
    });
    setShowJobForm(true);
    setMessage("");
  };

  const handleJobFormChange = (event) => {
    const { name, value, checked, type } = event.target;
    setJobForm((current) => ({
      ...current,
      [name]: type === "checkbox" ? checked : value,
    }));
  };

  const saveTargetJob = async (event) => {
    event.preventDefault();
    const payload = {
      job_title: jobForm.job_title,
      company_name: jobForm.company_name,
      jd_text: jobForm.jd_text,
      notes: jobForm.notes,
    };

    try {
      setLoading(true);

      if (editingJobId) {
        const response = await apiClient.put(
          `/api/target-jobs/${editingJobId}`,
          payload,
        );

        if (jobForm.is_active && !response.data.is_active) {
          await apiClient.post(`/api/target-jobs/${editingJobId}/activate`);
        }
      } else {
        await apiClient.post("/api/target-jobs", {
          ...payload,
          is_active: jobForm.is_active,
        });
      }

      setShowJobForm(false);
      setEditingJobId(null);
      setJobForm(EMPTY_JOB);
      await loadProfileData();
      setMessage("目标岗位已保存。");
    } catch (error) {
      console.error("save target job error:", error);
      setMessage(getFriendlyErrorMessage(error, "保存目标岗位失败。"));
    } finally {
      setLoading(false);
    }
  };

  const activateTargetJob = async (jobId) => {
    try {
      setLoading(true);
      await apiClient.post(`/api/target-jobs/${jobId}/activate`);
      await loadProfileData();
      setMessage("当前目标岗位已更新。");
    } catch (error) {
      console.error("activate target job error:", error);
      setMessage(getFriendlyErrorMessage(error, "设置当前目标岗位失败。"));
    } finally {
      setLoading(false);
    }
  };

  const deleteTargetJob = async (jobId) => {
    if (!window.confirm("确认删除这个目标岗位吗？")) {
      return;
    }

    try {
      setLoading(true);
      await apiClient.delete(`/api/target-jobs/${jobId}`);
      await loadProfileData();
      setMessage("目标岗位已删除。");
    } catch (error) {
      console.error("delete target job error:", error);
      setMessage(getFriendlyErrorMessage(error, "删除目标岗位失败。"));
    } finally {
      setLoading(false);
    }
  };

  const resumeFiles = files.filter((file) => file.category === "resume");
  const projectFiles = files.filter((file) => file.category === "project");
  const activeJob = targetJobs.find((job) => job.is_active);
  const basicProfileComplete = Boolean(
    profile.display_name?.trim() &&
      profile.target_direction?.trim() &&
      profile.self_introduction?.trim() &&
      profile.technical_skills?.length,
  );
  const completionItems = [
    ["基本资料", basicProfileComplete],
    ["简历文件", resumeFiles.length > 0],
    ["项目资料", projectFiles.length > 0],
    ["当前目标岗位", Boolean(activeJob)],
  ];

  return (
    <section className="profile-page">
      <h1>我的资料</h1>
      <p>维护个人介绍、目标岗位和知识库资料分类，供后续分析与问答使用。</p>

      <div className="profile-completion">
        {completionItems.map(([label, complete]) => (
          <div key={label} className={complete ? "is-complete" : "is-pending"}>
            <span>{label}</span>
            <strong>{complete ? "已完成" : "待完善"}</strong>
          </div>
        ))}
      </div>

      {message && <p className="message-text">{message}</p>}

      <div className="profile-section">
        <div className="profile-section-heading">
          <div>
            <h2>基本资料</h2>
            <p>技术栈可用逗号或换行分隔。</p>
          </div>
        </div>

        <form className="profile-form" onSubmit={saveProfile}>
          <label htmlFor="display-name">显示名称</label>
          <input
            id="display-name"
            name="display_name"
            value={profile.display_name || ""}
            onChange={handleProfileChange}
            maxLength={100}
          />

          <label htmlFor="target-direction">目标岗位方向</label>
          <input
            id="target-direction"
            name="target_direction"
            value={profile.target_direction || ""}
            onChange={handleProfileChange}
            maxLength={200}
          />

          <label htmlFor="self-introduction">自我介绍</label>
          <textarea
            id="self-introduction"
            name="self_introduction"
            value={profile.self_introduction || ""}
            onChange={handleProfileChange}
            rows={6}
            maxLength={5000}
          />

          <label htmlFor="technical-skills">技术栈标签</label>
          <textarea
            id="technical-skills"
            value={skillsText}
            onChange={(event) => setSkillsText(event.target.value)}
            rows={3}
            placeholder="Python, FastAPI, RAG, LangGraph"
          />

          <div className="profile-actions">
            <button type="submit" disabled={loading}>
              保存基本资料
            </button>
          </div>
        </form>
      </div>

      <div className="profile-section">
        <div className="profile-section-heading">
          <div>
            <h2>目标岗位</h2>
            <p>可保存多个 JD，同时只会有一个当前生效岗位。</p>
          </div>
          <button type="button" onClick={startCreateJob} disabled={loading}>
            新建岗位
          </button>
        </div>

        {showJobForm && (
          <form className="target-job-form" onSubmit={saveTargetJob}>
            <label htmlFor="job-title">岗位名称</label>
            <input
              id="job-title"
              name="job_title"
              value={jobForm.job_title}
              onChange={handleJobFormChange}
              maxLength={200}
              required
            />

            <label htmlFor="company-name">公司名称</label>
            <input
              id="company-name"
              name="company_name"
              value={jobForm.company_name}
              onChange={handleJobFormChange}
              maxLength={200}
            />

            <label htmlFor="jd-text">JD 文本</label>
            <textarea
              id="jd-text"
              name="jd_text"
              value={jobForm.jd_text}
              onChange={handleJobFormChange}
              rows={10}
              maxLength={50000}
              required
            />

            <label htmlFor="job-notes">备注</label>
            <textarea
              id="job-notes"
              name="notes"
              value={jobForm.notes}
              onChange={handleJobFormChange}
              rows={3}
              maxLength={5000}
            />

            {jobForm.is_active ? (
              <p className="job-active-option active-job-note">
                当前岗位已生效；删除后可以暂时不设置目标岗位。
              </p>
            ) : (
              <label className="job-active-option">
                <input
                  name="is_active"
                  type="checkbox"
                  checked={jobForm.is_active}
                  onChange={handleJobFormChange}
                />
                设置为当前目标岗位
              </label>
            )}

            <div className="profile-actions">
              <button type="submit" disabled={loading}>
                {editingJobId ? "保存修改" : "保存岗位"}
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={() => setShowJobForm(false)}
                disabled={loading}
              >
                取消
              </button>
            </div>
          </form>
        )}

        <div className="target-job-list">
          {targetJobs.length === 0 ? (
            <p className="empty-text">尚未保存目标岗位。</p>
          ) : (
            targetJobs.map((job) => (
              <article key={job.id} className="target-job-item">
                <div className="target-job-title">
                  <div>
                    <h3>{job.job_title}</h3>
                    <p>{job.company_name || "未填写公司"}</p>
                  </div>
                  {job.is_active && <strong>当前生效</strong>}
                </div>
                <p className="job-jd-preview">{job.jd_text}</p>
                {job.notes && <p className="job-notes">备注：{job.notes}</p>}
                <div className="profile-actions">
                  {!job.is_active && (
                    <button
                      type="button"
                      onClick={() => activateTargetJob(job.id)}
                      disabled={loading}
                    >
                      设为当前目标
                    </button>
                  )}
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => startEditJob(job)}
                    disabled={loading}
                  >
                    编辑
                  </button>
                  <button
                    type="button"
                    className="danger-button"
                    onClick={() => deleteTargetJob(job.id)}
                    disabled={loading}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))
          )}
        </div>
      </div>

      <div className="profile-section">
        <div className="profile-section-heading">
          <div>
            <h2>资料文件</h2>
            <p>文件仍由知识库统一上传、删除和建立索引。</p>
          </div>
          <button type="button" onClick={onOpenKnowledge}>
            前往知识库管理
          </button>
        </div>

        <div className="profile-file-groups">
          <div>
            <h3>简历文件</h3>
            {resumeFiles.length === 0 ? (
              <p className="empty-text">暂无简历文件。</p>
            ) : (
              <ul>
                {resumeFiles.map((file) => (
                  <li key={file.file_id}>{file.filename}</li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h3>项目资料</h3>
            {projectFiles.length === 0 ? (
              <p className="empty-text">暂无项目资料。</p>
            ) : (
              <ul>
                {projectFiles.map((file) => (
                  <li key={file.file_id}>{file.filename}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

export default Profile;
