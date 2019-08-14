"""
He, Xiangnan, et al. "Neural collaborative filtering." Proceedings of the 26th International Conference on World Wide Web. International World Wide Web Conferences Steering Committee, 2017.
"""
import os
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from models.BaseModel import BaseModel
from models.GMF import GMF
from models.MLP import MLP
from utils.Params import Params

class NeuMF(BaseModel):
    def __init__(self, model_conf, num_user, num_item, device):
        super(NeuMF, self).__init__()
        self.use_pretrain = model_conf.user_pretrain
        self.num_users = num_user
        self.num_items = num_item
        self.merge_alpha = model_conf.merge_alpha
        if self.use_pretrain:
            save_dir = model_conf.exp_conf['save_dir']
            self.gmf_save_num = model_conf.gmf_save_num
            self.mlp_save_num = model_conf.mlp_save_num
            self.gmf = self.load_pretrained_model(save_dir, 'gmf', self.gmf_save_num)
            self.mlp = self.load_pretrained_model(save_dir, 'mlp', self.mlp_save_num)
        else:
            self.gmf = GMF(model_conf.gmf_conf, num_user, num_item, device)
            self.mlp = MLP(model_conf.mlp_conf, num_user, num_item, device)

        self.device = device
        self.to(device)

    def load_pretrained_model(self, save_dir, model, num):
        assert model in ['gmf', 'mlp'], 'Pretrained model name incorrect. (Should be gmf or mlp)'

        model_path = os.path.join(save_dir, model)
        save_list = os.listdir(model_path)
        save_nums = [int(x[0]) for x in save_list]
        assert num in save_nums, 'Save # %d not exists' % num
        model_num_path = os.path.join(model_path, save_list[num])
        if model == 'gmf':
            model_conf = Params(os.path.join(model_num_path, 'config.json'))
            model = GMF(model_conf, self.num_users, self.num_items, self.device)
            pretrained_model = model.load_state_dict(torch.load(model_num_path))
        elif model == 'mlp':
            model_conf = Params(os.path.join(model_num_path, 'config.json'))
            model = MLP(model_conf, self.num_users, self.num_items, self.device)
            pretrained_model = model.load_state_dict(torch.load(model_num_path))
        else:
            raise ValueError('Pretrained model name incorrect. (Should be gmf or mlp)')

        return pretrained_model

    def forward(self, user_ids, item_ids):
        gmf_output = self.gmf(user_ids, item_ids)
        mlp_output = self.mlp(user_ids, item_ids)
        out = gmf_output * self.merge_alpha + mlp_output * (1 - self.merge_alpha)

        return out

    def train_one_epoch(self, dataset, optimizer, batch_size, verbose):
        # user, item, rating pairs
        user_ids, item_ids, ratings = dataset.generate_pointwise_data()

        num_training = len(user_ids)
        num_batches = int(np.ceil(num_training / batch_size))

        perm = np.random.permutation(num_training)

        loss = 0.0
        for b in range(num_batches):
            optimizer.zero_grad()

            if (b + 1) * batch_size >= num_training:
                batch_idx = perm[b * batch_size:]
            else:
                batch_idx = perm[b * batch_size: (b + 1) * batch_size]

            batch_users = user_ids[batch_idx]
            batch_items = item_ids[batch_idx]
            batch_ratings = ratings[batch_idx]

            pred_ratings = self.forward(batch_users, batch_items)

            batch_loss = F.binary_cross_entropy(pred_ratings, batch_ratings)
            batch_loss.backward()
            optimizer.step()

            loss += batch_loss

            if verbose and b % 50 == 0:
                print('(%3d / %3d) loss = %.4f' % (b, num_batches, batch_loss))
        return loss

    def predict(self, dataset, test_batch_size):
        eval_users = []
        eval_items = []
        eval_candidates = dataset.eval_items
        for u in eval_candidates:
            eval_users += [u] * len(eval_candidates[u])
            eval_items += eval_candidates[u]
        eval_users = torch.LongTensor(eval_users).to(self.device)
        eval_items = torch.LongTensor(eval_items).to(self.device)
        pred_matrix = torch.full((dataset.num_users, dataset.num_items), float('-inf'))

        num_data = len(eval_items)
        num_batches = int(np.ceil(num_data / test_batch_size))
        perm = list(range(num_data))
        with torch.no_grad():
            for b in range(num_batches):
                if (b + 1) * test_batch_size >= num_data:
                    batch_idx = perm[b * test_batch_size:]
                else:
                    batch_idx = perm[b * test_batch_size: (b + 1) * test_batch_size]
                batch_users, batch_items = eval_users[batch_idx], eval_items[batch_idx]
                pred_matrix[batch_users, batch_items] = self.forward(batch_users, batch_items)

        return pred_matrix
