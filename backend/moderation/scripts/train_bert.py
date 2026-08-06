import json, torch, os
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
from torch.utils.data import Dataset, DataLoader
from transformers import AutoTokenizer, AutoModelForSequenceClassification, get_linear_schedule_with_warmup
from tqdm import tqdm

def load_jsonl(path):
    with open(path, 'r', encoding='utf-8') as f:
        return [json.loads(line) for line in f]

train_data = load_jsonl(r'D:\code\mindglass\backend\moderation\data\train.jsonl')
val_data = load_jsonl(r'D:\code\mindglass\backend\moderation\data\val.jsonl')

model_name = r'D:\ai\bert-base-chinese'
tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=2, local_files_only=True)
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model.to(device)
print(f'Device: {device}, Model loaded from {model_name}')

class ModDS(Dataset):
    def __init__(self, data, tok, ml=128):
        self.data, self.tok, self.ml = data, tok, ml
    def __len__(self):
        return len(self.data)
    def __getitem__(self, i):
        enc = self.tok(self.data[i]['text'], max_length=self.ml, padding='max_length', truncation=True, return_tensors='pt')
        return {'input_ids': enc['input_ids'].squeeze(), 'attention_mask': enc['attention_mask'].squeeze(), 'label': torch.tensor(self.data[i]['label'], dtype=torch.long)}

train_loader = DataLoader(ModDS(train_data, tokenizer), batch_size=16, shuffle=True)
val_loader = DataLoader(ModDS(val_data, tokenizer), batch_size=16, shuffle=False)

optimizer = torch.optim.AdamW(model.parameters(), lr=2e-5, weight_decay=0.01)
total_steps = len(train_loader) * 3
scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=int(total_steps*0.1), num_training_steps=total_steps)

# 类别不平衡处理：计算 class weight（样本数的反比）
n0 = sum(1 for d in train_data if d['label'] == 0)
n1 = sum(1 for d in train_data if d['label'] == 1)
total = n0 + n1
# weight = total / (num_classes * count_per_class)，让少数类获得更大权重
w0 = total / (2 * n0)
w1 = total / (2 * n1)
class_weights = torch.tensor([w0, w1], dtype=torch.float32).to(device)
print(f'Class weights: label0={w0:.4f} ({n0} samples), label1={w1:.4f} ({n1} samples)')
loss_fn = torch.nn.CrossEntropyLoss(weight=class_weights)

history = []
for epoch in range(3):
    model.train(); tl = tc = tt = 0
    for b in tqdm(train_loader, desc=f'Ep {epoch+1} Train'):
        ids, mask, lab = b['input_ids'].to(device), b['attention_mask'].to(device), b['label'].to(device)
        optimizer.zero_grad()
        out = model(input_ids=ids, attention_mask=mask)
        logits = out.logits if hasattr(out, 'logits') else out[0]
        loss = loss_fn(logits, lab)
        loss.backward(); optimizer.step(); scheduler.step()
        tl += loss.item(); tc += (torch.argmax(logits,1)==lab).sum().item(); tt += lab.size(0)

    model.eval(); vl = vc = vt = 0
    with torch.no_grad():
        for b in val_loader:
            ids, mask, lab = b['input_ids'].to(device), b['attention_mask'].to(device), b['label'].to(device)
            out = model(input_ids=ids, attention_mask=mask)
            logits = out.logits if hasattr(out, 'logits') else out[0]
            loss = loss_fn(logits, lab)
            vl += loss.item(); vc += (torch.argmax(logits,1)==lab).sum().item(); vt += lab.size(0)

    h = {'epoch': epoch+1, 'train_loss': tl/len(train_loader), 'train_acc': tc/tt, 'val_loss': vl/len(val_loader), 'val_acc': vc/vt}
    history.append(h)
    print(f"Ep {epoch+1}: train_loss={h['train_loss']:.4f} train_acc={h['train_acc']:.4f} val_loss={h['val_loss']:.4f} val_acc={h['val_acc']:.4f}")

out_dir = r'D:\code\mindglass\backend\moderation\output\checkpoint\final'
os.makedirs(out_dir, exist_ok=True)
model.save_pretrained(out_dir)
tokenizer.save_pretrained(out_dir)
with open(f'{out_dir}/training_history.json','w',encoding='utf-8') as f: json.dump(history,f,indent=2)
print(f'Model saved to {out_dir}')
print('Done!')
