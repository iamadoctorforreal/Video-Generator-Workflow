import json

# =============================================================================
#  n8n Workflow Generator — Ultimate Hybrid Video Generator
#
#  Supports:
#  - Up to 10 local Scene Media uploads (File fields)
#  - Or Media URLs (Text area)
#  - Local Voiceover & Music uploads
#  - Or Voiceover & Music URLs
# =============================================================================

# ─── 1. FORM TRIGGER ─────────────────────────────────────────────────────────
form_fields = [
    {"fieldLabel": "Script (one paragraph per scene, separated by blank line)", "fieldType": "textarea", "requiredField": True},
    {"fieldLabel": "Media URLs (one per line, alternative to local uploads)", "fieldType": "textarea"},
]

# Add 10 individual scene upload fields
for i in range(1, 11):
    form_fields.append({
        "fieldLabel": f"Scene {i} Media (Local Upload)",
        "fieldType": "file"
    })

# Audio & Settings
form_fields.extend([
    {"fieldLabel": "Voiceover File (Local Upload)", "fieldType": "file"},
    {"fieldLabel": "Voiceover URL", "fieldType": "text"},
    {"fieldLabel": "Music File (Local Upload)", "fieldType": "file"},
    {"fieldLabel": "Music URL", "fieldType": "text"},
    {"fieldLabel": "AI Voice", "fieldType": "dropdown", "fieldOptions": {"values": [{"option": "af_bella"}, {"option": "am_adam"}]}},
    {"fieldLabel": "Generate AI Voiceover?", "fieldType": "dropdown", "fieldOptions": {"values": [{"option": "true"}, {"option": "false"}]}},
    {"fieldLabel": "Add Captions?", "fieldType": "dropdown", "fieldOptions": {"values": [{"option": "true"}, {"option": "false"}]}},
    {"fieldLabel": "Add Background Music?", "fieldType": "dropdown", "fieldOptions": {"values": [{"option": "true"}, {"option": "false"}]}}
])

form_node = {
    "parameters": {
        "formTitle": "Video Generator - Studio Mode",
        "formDescription": "Upload up to 10 scene images/videos directly, or paste URLs. Leave blank scenes to get a dark background.",
        "formFields": {"values": form_fields},
        "options": {}
    },
    "type": "n8n-nodes-base.formTrigger",
    "typeVersion": 2.5,
    "position": [-500, 0],
    "id": "form-trigger-1",
    "name": "Advanced Form Trigger",
    "webhookId": "22222222-2222-2222-2222-222222222222"
}

nodes = [form_node]
connections = {}

# ─── 2. BUILD SEQUENTIAL UPLOAD CHAIN FOR 10 SCENES + AUDIO ──────────────────
# We build a linear chain of IF -> Upload -> Merge for every possible binary file
# This guarantees exact ordering and avoids parallel merge issues in n8n.

binary_fields = [f"Scene {i} Media (Local Upload)" for i in range(1, 11)] + [
    "Voiceover File (Local Upload)",
    "Music File (Local Upload)"
]

prev_node = "Advanced Form Trigger"
x_pos = -200
y_pos = 0

for field_name in binary_fields:
    # URL endpoint depends on field type
    if "Scene" in field_name:
        endpoint = "/upload-image"
        # We need a safe JS property name to access the binary data (n8n usually makes it lowercase with underscores or keeps it verbatim)
        # We use a loose match in Object.keys()
    elif "Voiceover" in field_name:
        endpoint = "/upload-voiceover"
    else:
        endpoint = "/upload-music"

    # IF Node
    if_node = {
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": False, "leftValue": "", "typeValidation": "loose", "version": 2},
                "conditions": [{
                    "id": "check-binary",
                    "leftValue": f"={{{{ Object.keys($('Advanced Form Trigger').item.binary || {{}}).some(k => k === '{field_name}') }}}}",
                    "rightValue": True,
                    "operator": {"type": "boolean", "operation": "equals"}
                }],
                "combinator": "and"
            }
        },
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": [x_pos, y_pos],
        "id": f"if-{field_name}",
        "name": f"Has {field_name}?"
    }
    
    # Upload Node
    upload_node = {
        "parameters": {
            "method": "POST",
            "url": f"http://video-generator:8000{endpoint}",
            "sendBody": True,
            "contentType": "multipart-form-data",
            "bodyParameters": {
                "parameters": [{
                    "name": "file",
                    "parameterType": "formBinaryData",
                    "inputDataFieldName": f"={{{{ Object.keys($('Advanced Form Trigger').item.binary).find(k => k === '{field_name}') }}}}"
                }]
            }
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.3,
        "position": [x_pos + 300, y_pos - 100],
        "id": f"upload-{field_name}",
        "name": f"Upload {field_name}"
    }
    
    # Set Node (saves the uploaded filename to the item stream so the final code node can read it)
    set_node = {
        "parameters": {
            "assignments": {
                "assignments": [
                    {
                        "id": "1",
                        "name": f"uploaded_{field_name.replace(' ', '_')}",
                        "value": "={{ $json.filename }}",
                        "type": "string"
                    }
                ]
            },
            "options": {}
        },
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
        "position": [x_pos + 600, y_pos - 100],
        "id": f"set-{field_name}",
        "name": f"Save {field_name}"
    }

    # Merge Node (brings True/False paths back together)
    merge_node = {
        "parameters": {"mode": "passThrough", "output": "first"},
        "type": "n8n-nodes-base.merge",
        "typeVersion": 3,
        "position": [x_pos + 900, y_pos],
        "id": f"merge-{field_name}",
        "name": f"Merge {field_name}"
    }

    # Add to nodes list
    nodes.extend([if_node, upload_node, set_node, merge_node])
    
    # Connect
    if prev_node not in connections: connections[prev_node] = {"main": [[]]}
    connections[prev_node]["main"][0].append({"node": if_node["name"], "type": "main", "index": 0})
    
    connections[if_node["name"]] = {
        "main": [
            [{"node": upload_node["name"], "type": "main", "index": 0}], # True
            [{"node": merge_node["name"], "type": "main", "index": 0}]   # False
        ]
    }
    connections[upload_node["name"]] = {"main": [[{"node": set_node["name"], "type": "main", "index": 0}]]}
    connections[set_node["name"]] = {"main": [[{"node": merge_node["name"], "type": "main", "index": 0}]]}
    
    # Advance
    prev_node = merge_node["name"]
    x_pos += 1200

# ─── 3. FINAL CODE NODE TO BUILD PAYLOAD ──────────────────────────────────────

code_node = {
    "parameters": {
        "jsCode": f"""
const form = $('Advanced Form Trigger').item.json;
const stream = $input.first().json; // accumulated from Set nodes

const rawScript = form["Script (one paragraph per scene, separated by blank line)"] || "";
const rawMediaUrls = form["Media URLs (one per line, alternative to local uploads)"] || "";

const scriptLines = rawScript.split(/\\r?\\n\\r?\\n/).map(s => s.trim()).filter(Boolean);
const urlLines = rawMediaUrls.split(/\\r?\\n/).map(s => s.trim()).filter(Boolean);

const scenes = scriptLines.map((text, i) => {{
  // 1. Check if a local file was uploaded for this specific scene (1-indexed)
  const localFileName = stream[`uploaded_Scene_${{i+1}}_Media_(Local_Upload)`];
  
  // 2. Fallback to URL if provided
  const urlFallback = urlLines[i];
  
  return {{
    text,
    media_name: localFileName || urlFallback || "detect"
  }};
}});

const toBool = (val, def) => (val === undefined || val === "") ? def : val === "true";
const generateVo = toBool(form["Generate AI Voiceover?"], true);

return [{{
  json: {{
    scenes,
    voice: form["AI Voice"] || "af_bella",
    generate_voiceover: generateVo,
    uploaded_voiceover: generateVo ? null : stream["uploaded_Voiceover_File_(Local_Upload)"],
    voiceover_url: generateVo ? null : form["Voiceover URL"],
    add_captions: toBool(form["Add Captions?"], true),
    add_background_music: toBool(form["Add Background Music?"], true),
    bg_music_file: stream["uploaded_Music_File_(Local_Upload)"],
    bg_music_url: form["Music URL"]
  }}
}}];
"""
    },
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [x_pos, 0],
    "id": "final-code-node",
    "name": "Format JSON Payload"
}
nodes.append(code_node)
connections[prev_node] = {"main": [[{"node": "Format JSON Payload", "type": "main", "index": 0}]]}

# ─── 4. API CALLS ─────────────────────────────────────────────────────────────

api_node = {
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
    "position": [x_pos + 300, 0],
    "id": "api-node",
    "name": "Send to FastAPI"
}

wait_node = {
    "parameters": {"resume": "webhook", "options": {}},
    "type": "n8n-nodes-base.wait",
    "typeVersion": 1.1,
    "position": [x_pos + 600, 0],
    "id": "wait-node",
    "name": "Wait for Video Completion",
    "webhookId": "00000000-0000-0000-0000-000000000000"
}

download_node = {
    "parameters": {
        "method": "GET",
        "url": "={{ $json.body.video_url }}",
        "responseFormat": "file",
        "options": {}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.3,
    "position": [x_pos + 900, 0],
    "id": "download-node",
    "name": "Download Video"
}

gdrive_node = {
    "parameters": {
        "operation": "upload",
        "fileContent": "data",
        "name": "={{ $('Wait for Video Completion').item.json.body.filename || 'final_video.mp4' }}",
        "options": {}
    },
    "type": "n8n-nodes-base.googleDrive",
    "typeVersion": 3,
    "position": [x_pos + 1200, 0],
    "id": "gdrive-node",
    "name": "Upload to Google Drive",
    "credentials": {"googleDriveOAuth2Api": {"id": "", "name": "Google Drive account"}}
}

nodes.extend([api_node, wait_node, download_node, gdrive_node])
connections["Format JSON Payload"] = {"main": [[{"node": "Send to FastAPI", "type": "main", "index": 0}]]}
connections["Send to FastAPI"] = {"main": [[{"node": "Wait for Video Completion", "type": "main", "index": 0}]]}
connections["Wait for Video Completion"] = {"main": [[{"node": "Download Video", "type": "main", "index": 0}]]}
connections["Download Video"] = {"main": [[{"node": "Upload to Google Drive", "type": "main", "index": 0}]]}

# ─── SAVE TO FILE ─────────────────────────────────────────────────────────────

workflow = {
    "name": "Ultimate Ultimate Video Generator (10 Scenes + Audio)",
    "nodes": nodes,
    "connections": connections,
    "active": False,
    "settings": {"executionOrder": "v1"}
}

with open("n8n_workflow_updated.json", "w") as f:
    json.dump(workflow, f, indent=2)

print(f"Done! Created ultimate workflow with {len(nodes)} nodes.")
