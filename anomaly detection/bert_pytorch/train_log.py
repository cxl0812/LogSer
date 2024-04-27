import pickle
import time
from torch.utils.data import DataLoader
from bert_pytorch.model import BERT
from bert_pytorch.trainer import BERTTrainer
from bert_pytorch.dataset import LogDataset, WordVocab
from bert_pytorch.dataset.sample import generate_train_valid
from bert_pytorch.dataset.utils import save_parameters

import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import torch
import tqdm
import gc

class Trainer():
    def __init__(self, options):
        self.device = options["device"]
        self.model_dir = options["model_dir"]
        self.model_path = options["model_path"]
        self.increment_model_path = options["increment_model_path"]
        self.increment_model_dir = options["increment_model_dir"]
        self.vocab_path = options["vocab_path"]
        self.output_path = options["output_dir"]
        self.window_size = options["window_size"]
        self.adaptive_window = options["adaptive_window"]
        self.sample_ratio = options["train_ratio"]
        self.valid_ratio = options["valid_ratio"]
        self.seq_len = options["seq_len"]
        self.max_len = options["max_len"]
        self.corpus_lines = options["corpus_lines"]
        self.on_memory = options["on_memory"]
        self.batch_size = options["batch_size"]
        self.num_workers = options["num_workers"]
        self.lr = options["lr"]
        self.adam_beta1 = options["adam_beta1"]
        self.adam_beta2 = options["adam_beta2"]
        self.adam_weight_decay = options["adam_weight_decay"]
        self.with_cuda = options["with_cuda"]
        self.cuda_devices = options["cuda_devices"]
        self.log_freq = options["log_freq"]
        self.epochs = options["epochs"]
        self.hidden = options["hidden"]
        self.layers = options["layers"]
        self.attn_heads = options["attn_heads"]
        self.is_logkey = options["is_logkey"]
        self.is_time = options["is_time"]
        self.is_param = options["is_param"]
        self.is_increment = options["is_increment"]
        self.logname = options["logname"]
        self.scale = options["scale"]
        self.scale_path = options["scale_path"]
        self.n_epochs_stop = options["n_epochs_stop"]
        self.hypersphere_loss = options["hypersphere_loss"]
        self.mask_ratio = options["mask_ratio"]
        self.min_len = options['min_len']

        print("Save options parameters")
        if (self.is_increment):
            save_parameters(options, self.increment_model_dir + "parameters.txt")
        else:
            save_parameters(options, self.model_dir + "parameters.txt")

    def read_pickle(self, log_name, label_type):
        if label_type == 'normal':
            with open(self.output_path+log_name+'_embeddings_normal.pickle', 'rb') as f:
                p_data = pickle.load(f)
            with open(self.output_path+log_name+'_with_template_embeddings_normal.pickle', 'rb') as f:
                t_and_p_data = pickle.load(f)
        else:
            with open(self.output_path+log_name+'_embeddings_abnormal.pickle', 'rb') as f:
                p_data = pickle.load(f)
            with open(self.output_path+log_name+'_with_template_embeddings_abnormal.pickle', 'rb') as f:
                t_and_p_data = pickle.load(f)
        np_p_data = dict()
        np_t_and_p_data = dict()
        for idex, item in p_data.items():
            np_p_data[idex] = item.cpu().numpy()
        for idex, item in t_and_p_data.items():
            np_t_and_p_data[idex] = item.cpu().numpy()
        return np_p_data, np_t_and_p_data

    def train(self):

        print("Loading vocab", self.vocab_path)
        vocab = WordVocab.load_vocab(self.vocab_path)
        print("vocab Size: ", len(vocab))

        if (self.is_increment):
            train_path = self.output_path + "increment_train"
        else:
            train_path = self.output_path + "train"

        # 划分训练集train和验证集valid
        print("\nLoading Train Dataset")
        logkey_train, logkey_valid, time_train, time_valid = generate_train_valid(train_path, window_size=self.window_size,
                                     adaptive_window=self.adaptive_window,
                                     valid_size=self.valid_ratio,
                                     sample_ratio=self.sample_ratio,
                                     scale=self.scale,
                                     scale_path=self.scale_path,
                                     seq_len=self.seq_len,
                                     min_len=self.min_len
                                    )

        parameter_embedding, template_and_parameter_embedding = self.read_pickle(log_name=self.logname, label_type="normal")

        # 在该部分对日志序列进行mask处理
        train_dataset = LogDataset(logkey_train,time_train, vocab, seq_len=self.seq_len, 
                                   parameter_embedding=parameter_embedding, template_and_parameter_embedding=template_and_parameter_embedding,
                                   corpus_lines=self.corpus_lines, on_memory=self.on_memory, mask_ratio=self.mask_ratio)

        print("\nLoading valid Dataset")
        # valid_dataset = generate_train_valid(self.output_path + "train", window_size=self.window_size,
        #                              adaptive_window=self.adaptive_window,
        #                              sample_ratio=self.valid_ratio)

        valid_dataset = LogDataset(logkey_valid, time_valid, vocab, seq_len=self.seq_len, 
                                   parameter_embedding=parameter_embedding, template_and_parameter_embedding=template_and_parameter_embedding,
                                   on_memory=self.on_memory, mask_ratio=self.mask_ratio)
        
        print("Creating Dataloader")
        self.train_data_loader = DataLoader(train_dataset, batch_size=self.batch_size, num_workers=self.num_workers,
                                      collate_fn=train_dataset.collate_fn, drop_last=True)
        self.valid_data_loader = DataLoader(valid_dataset, batch_size=self.batch_size, num_workers=self.num_workers,
                                       collate_fn=train_dataset.collate_fn, drop_last=True)
        del train_dataset
        del valid_dataset
        del logkey_train
        del logkey_valid
        del time_train
        del time_valid
        gc.collect()

        # 创建bert模型，并在模型设计好embeading嵌入表示
        print("Building BERT model")
        bert = BERT(len(vocab), max_len=self.max_len, hidden=self.hidden, n_layers=self.layers, attn_heads=self.attn_heads,
                    is_logkey=self.is_logkey, is_time=self.is_time)
            
        # 在该部分设计两个预训练任务
        print("Creating BERT Trainer")
        self.trainer = BERTTrainer(bert, len(vocab), train_dataloader=self.train_data_loader, valid_dataloader=self.valid_data_loader,
                              lr=self.lr, betas=(self.adam_beta1, self.adam_beta2), weight_decay=self.adam_weight_decay,
                              with_cuda=self.with_cuda, cuda_devices=self.cuda_devices, log_freq=self.log_freq,
                              is_logkey=self.is_logkey, is_time=self.is_time, is_param=self.is_param, is_increment=self.is_increment,
                              model_path=self.model_path, hypersphere_loss=self.hypersphere_loss)

        self.start_iteration(surfix_log="log2")

        self.plot_train_valid_loss("_log2")

    def start_iteration(self, surfix_log):
        print("Training Start")
        best_loss = float('inf')
        epochs_no_improve = 0
        # best_center = None
        # best_radius = 0
        # total_dist = None
        for epoch in range(self.epochs):
            print("\n")
            start_time = time.time()
            if self.hypersphere_loss:
                center = self.calculate_center([self.train_data_loader, self.valid_data_loader])
                # center = self.calculate_center([self.train_data_loader])
                self.trainer.hyper_center = center
            
            # 模型训练
            _, train_dist = self.trainer.train(epoch)
            avg_loss, valid_dist = self.trainer.valid(epoch)
            if (self.is_increment):
                self.trainer.save_log(self.increment_model_dir, surfix_log)
            else:
                self.trainer.save_log(self.model_dir, surfix_log)

            if self.hypersphere_loss:
                self.trainer.radius = self.trainer.get_radius(train_dist + valid_dist, self.trainer.nu)

            # save model after 10 warm up epochs
            if avg_loss < best_loss:
                best_loss = avg_loss
                if (self.is_increment):
                    self.trainer.save(self.increment_model_path)
                else:
                    self.trainer.save(self.model_path)
                epochs_no_improve = 0

                if epoch > 10 and self.hypersphere_loss:
                    best_center = self.trainer.hyper_center
                    best_radius = self.trainer.radius
                    total_dist = train_dist + valid_dist

                    if best_center is None:
                        raise TypeError("center is None")

                    print("best radius", best_radius)
                    if (self.is_increment):
                        best_center_path = self.increment_model_dir + "best_center.pt"
                    else:
                        best_center_path = self.model_dir + "best_center.pt"
                    print("Save best center", best_center_path)
                    torch.save({"center": best_center, "radius": best_radius}, best_center_path)
                    
                    if (self.is_increment):
                        total_dist_path = self.increment_model_dir + "best_total_dist.pt"
                    else:
                        total_dist_path = self.model_dir + "best_total_dist.pt"
                    print("save total dist: ", total_dist_path)
                    torch.save(total_dist, total_dist_path)
            else:
                epochs_no_improve += 1
            
            end_time = time.time()
            print("耗时: {:.2f}秒".format(end_time - start_time))

            if epochs_no_improve == self.n_epochs_stop:
                print("Early stopping")
                break

    def calculate_center(self, data_loader_list):
        print("start calculate center")
        # model = torch.load(self.model_path)
        # model.to(self.device)
        with torch.no_grad():
            outputs = 0
            total_samples = 0
            for data_loader in data_loader_list:
                totol_length = len(data_loader)
                data_iter = tqdm.tqdm(enumerate(data_loader), total=totol_length)
                for i, data in data_iter:
                    data = {key: value.to(self.device) for key, value in data.items()}

                    # result = self.trainer.model.forward(data["bert_input"], data["time_input"])
                    if self.is_param:
                        result = self.trainer.model.forward(data["bert_input"], data["time_input"], data["param_embedding"])
                    else:
                        result = self.trainer.model.forward(data["bert_input"], data["time_input"])
                    cls_output = result["cls_output"]

                    outputs += torch.sum(cls_output.detach().clone(), dim=0)
                    total_samples += cls_output.size(0)

        center = outputs / total_samples

        return center

    def plot_train_valid_loss(self, surfix_log):
        if (self.is_increment):
            train_loss = pd.read_csv(self.increment_model_dir + f"train{surfix_log}.csv")
            valid_loss = pd.read_csv(self.increment_model_dir + f"valid{surfix_log}.csv")
        else:
            train_loss = pd.read_csv(self.model_dir + f"train{surfix_log}.csv")
            valid_loss = pd.read_csv(self.model_dir + f"valid{surfix_log}.csv")
        sns.lineplot(x="epoch", y="loss", data=train_loss, label="train loss")
        sns.lineplot(x="epoch", y="loss", data=valid_loss, label="valid loss")
        plt.title("epoch vs train loss vs valid loss")
        plt.legend()
        if (self.is_increment):
            plt.savefig(self.increment_model_dir + "train_valid_loss.png")
        else:
            plt.savefig(self.model_dir + "train_valid_loss.png")
        plt.show()
        print("plot done")





