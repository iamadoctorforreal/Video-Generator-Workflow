import json
import os

filepath = r"C:\Users\RUKAYYAH IBRAHIM\Desktop\kokoro\n8n_workflow.json"
with open(filepath, 'r', encoding='utf-8') as f:
    data = json.load(f)

# Find the form node
form_node = next(n for n in data['nodes'] if n['type'] == 'n8n-nodes-base.formTrigger')
fields = form_node['parameters']['formFields']['values']

# Make sure we don't duplicate
new_fields = [
    {
        "fieldLabel": "Orientation",
        "fieldType": "dropdown",
        "fieldOptions": {
            "values": [{"option": "landscape"}, {"option": "portrait"}]
        }
    },
    {
        "fieldLabel": "Caption Position",
        "fieldType": "dropdown",
        "fieldOptions": {
            "values": [{"option": "bottom"}, {"option": "center"}, {"option": "top"}]
        }
    }
]

# Keep only Script and voice if they exist
fields = [f for f in fields if f['fieldLabel'] in ["Script (one line per scene)", "voice"]]
fields.extend(new_fields)
form_node['parameters']['formFields']['values'] = fields

# Find the code node
code_node = next(n for n in data['nodes'] if n['type'] == 'n8n-nodes-base.code')
code_node['parameters']['jsCode'] = """const input = $input.first().json;
const rawScript = input["Script (one line per scene)"] || "";
const voice = input["voice"] || "af_bella";
const orientation = input["Orientation"] || "landscape";
const caption_position = input["Caption Position"] || "bottom";

const scenes = rawScript
  .split(/\\r?\\n\\r?\\n/)
  .map(s => s.trim())
  .filter(s => s.length > 0)
  .map(text => ({
    text: text,
    media_name: "detect"
  }));
return [{
  json: {
    scenes: scenes,
    voice: voice,
    add_captions: true,
    add_effects: true,
    caption_position: caption_position,
    orientation: orientation
  }
}];"""

with open(filepath, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)

print("Updated workflow JSON safely!")
