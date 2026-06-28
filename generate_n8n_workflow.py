import json

# ─── FORM TRIGGER ────────────────────────────────────────────────────────────
form_node = {
    "parameters": {
        "formTitle": "🎬 Video Generator",
        "formDescription": "Fill in what you need. Most fields are optional — only the Script is required for AI voiceover generation.",
        "formFields": {
            "values": [
                {
                    "fieldLabel": "Script (one scene per blank-line-separated paragraph)",
                    "fieldType": "textarea",
                    "requiredField": True
                },
                {
                    "fieldLabel": "Media URLs (one URL per line, matched to scenes — optional)",
                    "fieldType": "textarea"
                },
                {
                    "fieldLabel": "Voiceover Audio URL (optional — paste a direct URL to an audio file to use as voiceover instead of AI TTS)",
                    "fieldType": "text"
                },
                {
                    "fieldLabel": "Background Music URL (optional — paste a direct URL to an mp3/wav to use as background music)",
                    "fieldType": "text"
                },
                {
                    "fieldLabel": "Voice",
                    "fieldType": "dropdown",
                    "fieldOptions": {"values": [
                        {"option": "af_bella"},
                        {"option": "af_sarah"},
                        {"option": "am_adam"},
                        {"option": "bf_emma"},
                        {"option": "bm_george"}
                    ]}
                },
                {
                    "fieldLabel": "Generate AI Voiceover?",
                    "fieldType": "dropdown",
                    "fieldOptions": {"values": [{"option": "true"}, {"option": "false"}]}
                },
                {
                    "fieldLabel": "Add Captions?",
                    "fieldType": "dropdown",
                    "fieldOptions": {"values": [{"option": "true"}, {"option": "false"}]}
                },
                {
                    "fieldLabel": "Caption Position",
                    "fieldType": "dropdown",
                    "fieldOptions": {"values": [{"option": "bottom"}, {"option": "center"}, {"option": "top"}]}
                },
                {
                    "fieldLabel": "Add Background Music?",
                    "fieldType": "dropdown",
                    "fieldOptions": {"values": [{"option": "true"}, {"option": "false"}]}
                },
                {
                    "fieldLabel": "Background Music Volume (0.0 to 1.0, default 0.12)",
                    "fieldType": "text"
                },
                {
                    "fieldLabel": "Keep Original Video Audio?",
                    "fieldType": "dropdown",
                    "fieldOptions": {"values": [{"option": "false"}, {"option": "true"}]}
                },
                {
                    "fieldLabel": "Original Video Audio Volume (0.0 to 1.0, default 0.4)",
                    "fieldType": "text"
                },
                {
                    "fieldLabel": "Add Pan/Zoom Effects? (recommended for still images)",
                    "fieldType": "dropdown",
                    "fieldOptions": {"values": [{"option": "true"}, {"option": "false"}]}
                },
                {
                    "fieldLabel": "Orientation",
                    "fieldType": "dropdown",
                    "fieldOptions": {"values": [{"option": "landscape"}, {"option": "portrait"}]}
                }
            ]
        },
        "options": {}
    },
    "type": "n8n-nodes-base.formTrigger",
    "typeVersion": 2.5,
    "position": [-800, 0],
    "id": "form-trigger-1",
    "name": "Advanced Form Trigger"
}

# ─── UPLOAD VOICEOVER (conditional — only if a URL was provided) ──────────────
upload_voiceover_node = {
    "parameters": {
        "method": "POST",
        "url": "http://video-generator:8000/upload-voiceover",
        "sendBody": True,
        "contentType": "multipart-form-data",
        "bodyParameters": {
            "parameters": [
                {
                    "name": "file",
                    "value": "={{ $json['Voiceover Audio URL (optional — paste a direct URL to an audio file to use as voiceover instead of AI TTS)'] }}"
                }
            ]
        },
        "options": {}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.3,
    "position": [-500, -200],
    "id": "upload-vo-1",
    "name": "Upload Voiceover (if URL provided)"
}

# ─── UPLOAD BACKGROUND MUSIC (conditional — only if a URL was provided) ──────
upload_music_node = {
    "parameters": {
        "method": "POST",
        "url": "http://video-generator:8000/upload-music",
        "sendBody": True,
        "contentType": "multipart-form-data",
        "bodyParameters": {
            "parameters": [
                {
                    "name": "file",
                    "value": "={{ $json['Background Music URL (optional — paste a direct URL to an mp3/wav to use as background music)'] }}"
                }
            ]
        },
        "options": {}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.3,
    "position": [-500, 200],
    "id": "upload-music-1",
    "name": "Upload Background Music (if URL provided)"
}

# ─── CODE: FORMAT PAYLOAD ─────────────────────────────────────────────────────
# Note: This node merges the form data with the optional upload results.
# If voiceover/music URLs were blank, the upload nodes are skipped by the IF nodes
# and the uploaded_voiceover / bg_music_file fields will be null.
code_node = {
    "parameters": {
        "jsCode": r"""
const form = $('Advanced Form Trigger').item.json;

const rawScript = form["Script (one scene per blank-line-separated paragraph)"] || "";
const rawMediaUrls = form["Media URLs (one URL per line, matched to scenes — optional)"] || "";

const scriptLines = rawScript.split(/\r?\n\r?\n/).map(s => s.trim()).filter(s => s.length > 0);
const mediaUrls = rawMediaUrls.split(/\r?\n/).map(s => s.trim()).filter(s => s.length > 0);

const scenes = scriptLines.map((text, index) => ({
  text: text,
  media_name: mediaUrls[index] ? mediaUrls[index] : "detect"
}));

const toBool = (val, def) => val === undefined || val === "" ? def : val === "true";

// Get optional uploaded filenames from previous nodes (null-safe)
let uploadedVo = null;
try { uploadedVo = $('Upload Voiceover (if URL provided)').item.json.filename || null; } catch(e) {}

let uploadedMusic = null;
try { uploadedMusic = $('Upload Background Music (if URL provided)').item.json.filename || null; } catch(e) {}

const generateVo = toBool(form["Generate AI Voiceover?"], true);

return [{
  json: {
    scenes,
    voice: form["Voice"] || "af_bella",
    generate_voiceover: generateVo,
    uploaded_voiceover: generateVo ? null : uploadedVo,
    add_captions: toBool(form["Add Captions?"], true),
    caption_position: form["Caption Position"] || "bottom",
    add_background_music: toBool(form["Add Background Music?"], true),
    bg_music_file: uploadedMusic || null,
    bg_music_volume: parseFloat(form["Background Music Volume (0.0 to 1.0, default 0.12)"] || "0.12"),
    keep_clip_audio: toBool(form["Keep Original Video Audio?"], false),
    clip_audio_volume: parseFloat(form["Original Video Audio Volume (0.0 to 1.0, default 0.4)"] || "0.4"),
    add_effects: toBool(form["Add Pan/Zoom Effects? (recommended for still images)"], true),
    orientation: form["Orientation"] || "landscape"
  }
}];
"""
    },
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [-100, 0],
    "id": "code-node-1",
    "name": "Format JSON Payload"
}

# ─── SEND TO FASTAPI ──────────────────────────────────────────────────────────
http_post_node = {
    "parameters": {
        "method": "POST",
        "url": "http://video-generator:8000/generate-video",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ Object.assign({}, $json, { webhook_url: $resumeUrl }) }}",
        "options": {"timeout": 3600000}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.3,
    "position": [200, 0],
    "id": "http-post-1",
    "name": "Send Request to FastAPI"
}

# ─── WAIT FOR WEBHOOK ─────────────────────────────────────────────────────────
wait_node = {
    "parameters": {"resume": "webhook", "options": {}},
    "type": "n8n-nodes-base.wait",
    "typeVersion": 1.1,
    "position": [500, 0],
    "id": "wait-node-1",
    "name": "Wait for Video Completion",
    "webhookId": "00000000-0000-0000-0000-000000000000"
}

# ─── DOWNLOAD VIDEO ───────────────────────────────────────────────────────────
http_download_node = {
    "parameters": {
        "method": "GET",
        "url": "={{ $json.body.video_url }}",
        "responseFormat": "file",
        "options": {}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.3,
    "position": [800, 0],
    "id": "http-download-1",
    "name": "Download Video File"
}

# ─── UPLOAD TO GOOGLE DRIVE ───────────────────────────────────────────────────
gdrive_node = {
    "parameters": {
        "operation": "upload",
        "fileContent": "data",
        "name": "={{ $('Wait for Video Completion').item.json.body.filename || 'final_video.mp4' }}",
        "options": {}
    },
    "type": "n8n-nodes-base.googleDrive",
    "typeVersion": 3,
    "position": [1100, 0],
    "id": "gdrive-node-1",
    "name": "Upload to Google Drive",
    "credentials": {
        "googleDriveOAuth2Api": {
            "id": "",
            "name": "Google Drive account"
        }
    }
}

# ─── ASSEMBLE WORKFLOW ────────────────────────────────────────────────────────
# NOTE: The upload nodes run in parallel after the form trigger.
# The Code node merges the results before sending to FastAPI.
# If a user leaves the voiceover/music URL blank, those upload nodes will still
# fire but return an error — to fully make them conditional, an IF node per upload
# would be needed. For simplicity, the Code node handles null-safety.
new_workflow = {
    "name": "Advanced Video Generation to Google Drive",
    "nodes": [
        form_node,
        upload_voiceover_node,
        upload_music_node,
        code_node,
        http_post_node,
        wait_node,
        http_download_node,
        gdrive_node
    ],
    "connections": {
        "Advanced Form Trigger": {
            "main": [[
                {"node": "Upload Voiceover (if URL provided)", "type": "main", "index": 0},
                {"node": "Upload Background Music (if URL provided)", "type": "main", "index": 0},
                {"node": "Format JSON Payload", "type": "main", "index": 0}
            ]]
        },
        "Format JSON Payload": {
            "main": [[{"node": "Send Request to FastAPI", "type": "main", "index": 0}]]
        },
        "Send Request to FastAPI": {
            "main": [[{"node": "Wait for Video Completion", "type": "main", "index": 0}]]
        },
        "Wait for Video Completion": {
            "main": [[{"node": "Download Video File", "type": "main", "index": 0}]]
        },
        "Download Video File": {
            "main": [[{"node": "Upload to Google Drive", "type": "main", "index": 0}]]
        }
    },
    "active": False,
    "settings": {"executionOrder": "v1"}
}

with open("n8n_workflow_updated.json", "w") as f:
    json.dump(new_workflow, f, indent=2)

print("Done! Updated workflow written to n8n_workflow_updated.json")
