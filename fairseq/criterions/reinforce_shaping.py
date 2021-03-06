# Copyright (c) Facebook, Inc. and its affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
#

from ctypes import util
import math
import torch
import torch.nn.functional as F
from fairseq import metrics
from dataclasses import dataclass, field

import collections
from collections import defaultdict
from fairseq import utils, search

from fairseq.criterions import FairseqCriterion, register_criterion
from torch.distributions import Categorical
from fairseq.scoring import bleu
import csv
import numpy

from fairseq.sequence_generator import SequenceGenerator


# @dataclass
# class SequencePenaltyCriterionConfig(FairseqDataclass):
#     sequence_ngram_n: int = field(
#         default=4,
#         metadata={"help": "number of repeated n-grams wanting to penalise"},
#     )
#     sequence_prefix_length: int = field(
#         default=50,
#         metadata={"help": "length of prefix input?"},
#     )
#     sequence_completion_length: int = field(
#         default=100,
#         metadata={"help": "how long the predicted sequence will be?"},
#     )
#     sequence_candidate_type: str = field(
#         default="repeat",
#         metadata={"help": "candidate type for penalty (repeat, random)"},
#     )
#     mask_p: float = field(
#         default=0.5,
#         metadata={"help": "float between 0 and 1 that identifies random candidates in sequence to penalize?"},
#     )


@register_criterion('reinforce_shaping')
class ReinforceShaping(FairseqCriterion):

    def __init__(self, task, multinomial_sample_train, mle_weight, delta_reward, lr):
        super().__init__(task)

        self.tgt_dict = task.tgt_dict
        self.lr = lr
        self.multinomial_sample_train = multinomial_sample_train
        self.mle_weight = mle_weight
        self.delta_reward = delta_reward

    @staticmethod
    def add_args(parser):
        """Add criterion-specific arguments to the parser."""
        # fmt: off
        parser.add_argument('--mle-weight', default='0', type=float, metavar='D',
                            help='MLE weight')
        parser.add_argument('--multinomial-sample-train', default='True', type=bool, metavar='D',
                            help="Multinomial Sample Train")
        parser.add_argument('--delta-reward', default='True', type=bool, metavar='D',
                            help="Reward shaping")

    def forward(self, model, sample, reduce=True):

        # sample mode
        #print('!!!RL loss.')
        model.eval()
        # src_dict = self.task.source_dictionary
        tgt_dict = self.tgt_dict
        eos_idx = tgt_dict.eos()
        sample_beam = 1
        search_strategy = (
            search.Sampling(tgt_dict, sampling_topk=sample_beam) if self.multinomial_sample_train else None
        )
        # max_len = 100
        translator = SequenceGenerator([model], tgt_dict=tgt_dict,
                                       beam_size=sample_beam, min_len=1, search_strategy=search_strategy)
        translator.cuda()
        ct = 0
        translations = []

        s = utils.move_to_cuda(sample)
        input = s['net_input']
        with torch.no_grad():
            hypos = translator.generate(
                [model],
                sample,
            )
        for i, id in enumerate(s['id'].data):
            src = input['src_tokens'].data[i, :]
            # remove padding from ref
            ref = utils.strip_pad(s['target'].data[i, :], tgt_dict.pad()) if s['target'] is not None else None
            translations.append((id, src, ref, hypos[i]))
            ct += 1
        # print("sample batch size:", ct)

        # MLE loss
        mle_net_output = model(**sample['net_input'])
        mle_lprobs = model.get_normalized_probs(mle_net_output, log_probs=True)
        mle_lprobs = mle_lprobs.view(-1, mle_lprobs.size(-1))
        mle_target = model.get_targets(sample, mle_net_output).view(-1)
        mle_loss = F.nll_loss(mle_lprobs, mle_target, size_average=False,
                              ignore_index=self.padding_idx, reduce=reduce)
        mle_tokens = sample['ntokens']
        avg_mle_loss = mle_loss / mle_tokens
        # print('avg_mle_loss:', avg_mle_loss)

        # RL loss
        batch_rl_loss = 0
        batch_tokens = 0
        id = 0
        result = []
        for sample_id, src_tokens, tgt_tokens, hypos in translations:
            # calculate bleu
            id += 1
            hypo = hypos[0]  # only extract the first hypo (beam1 or sample1)
            trans_tokens = hypo['tokens']
            if self.delta_reward:
                reward = self.compute_sentence_bleu(tgt_tokens.cpu(), trans_tokens.cpu()).cuda()
            else:
                reward = self.compute_sentence_total_bleu(tgt_tokens.cpu(), trans_tokens.cpu()).cuda()
            # print(reward.item())
            result.append((id, reward.tolist(), tgt_tokens.size(0), trans_tokens.size(0)))
            # one_sample loss calculation
            tgt_input_tokens = trans_tokens.new(trans_tokens.shape).fill_(0)
            assert trans_tokens[-1] == eos_idx
            tgt_input_tokens[0] = eos_idx
            tgt_input_tokens[1:] = trans_tokens[:-1]
            train_sample = {
                'net_input': {
                    'src_tokens': src_tokens.view(1, -1),
                    'src_lengths': torch.LongTensor(src_tokens.numel()).view(1, -1),
                    'prev_output_tokens': tgt_input_tokens.view(1, -1),
                },
                'target': trans_tokens.view(1, -1)
            }
            train_sample = utils.move_to_cuda(train_sample)
            net_output = model(**train_sample['net_input'])
            lprobs = model.get_normalized_probs(net_output, log_probs=True)
            lprobs = lprobs.view(-1, lprobs.size(-1))
            target = model.get_targets(train_sample, net_output).view(-1, 1)
            non_pad_mask = target.ne(tgt_dict.pad())
            lprob = -lprobs.gather(dim=-1, index=target)[non_pad_mask]
            # print(reward)
            rl_loss = torch.sum(lprob * reward)  # one sample loss
            # print(rl_loss)
            ntokens = len(train_sample['target'])

            batch_tokens += ntokens
            batch_rl_loss += rl_loss
        avg_rl_loss = batch_rl_loss / batch_tokens
        self.rl_weight = 1.0 - self.mle_weight
        with open('./results/reward/v0_m'+str(self.mle_weight)+'r'+str(self.rl_weight)+'_lr'+str(self.lr)+'_r.csv', 'a', newline='') as csv_file:
            csv_writer = csv.writer(csv_file)
            for r in result:
                csv_writer.writerow(r)
        # print('avg_rl_loss:', avg_rl_loss)
        if self.mle_weight:
            assert self.rl_weight
            total_loss = self.mle_weight * avg_mle_loss + self.rl_weight * avg_rl_loss
            total_tokens = batch_tokens + mle_tokens
        else:
            total_loss = avg_rl_loss
            total_tokens = batch_tokens
        logging_output = {
            'loss': utils.item(total_loss.data),
            'ntokens': total_tokens,
            'sample_size': total_tokens,
        }
        # print('total: ',total_loss)
        # print(total_tokens)
        with open('./results/loss/v0_m'+str(self.mle_weight)+'r'+str(self.rl_weight)+'_lr'+str(self.lr)+'_l.csv', 'a', newline='') as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow((avg_mle_loss.item(), avg_rl_loss.item(), total_loss.item(), total_tokens))
        return total_loss, total_tokens, logging_output

    def _get_ngrams(self, segment, max_order):
        ngram_counts = collections.Counter()
        for order in range(1, max_order + 1):
            for i in range(0, len(segment) - order + 1):
                ngram = tuple(segment[i:i + order])
                ngram_counts[ngram] += 1
        return ngram_counts

    def _bleu(self, y, y_hat, n=4):
        bleu_scores = torch.zeros((len(y_hat), n))

        # count reference ngrams
        ref_counts = defaultdict(int)
        for k in range(1, n + 1):
            for i in range(len(y) - k + 1):
                ref_counts[tuple(y[i:i + k])] += 1

        # for each partial sequence, 1) compute addition to # of correct
        # 2) apply brevity penalty
        # ngrams, magic stability numbers from pycocoeval
        ref_len = len(y)
        pred_counts = defaultdict(int)
        correct = torch.zeros(4)
        for i in range(1, len(y_hat) + 1):
            for k in range(i, max(-1, i - n), -1):
                # print i, k
                ngram = tuple(y_hat[k - 1:i])
                # UNK token hack. Must work for both indices and words.
                # if UNK_ID in ngram or 'UNK' in ngram:
                #     continue
                pred_counts[ngram] += 1
                if pred_counts[ngram] <= ref_counts.get(ngram, 0):
                    correct[len(ngram) - 1] += 1

            # compute partial bleu score
            bleu = 1.
            for j in range(n):
                possible = max(0, i - j)
                bleu *= float(correct[j] + 1.) / (possible + 1.)
                bleu_scores[i - 1, j] = bleu ** (1. / (j + 1))

            # brevity penalty
            if i < ref_len:
                ratio = (i + 1e-15) / (ref_len + 1e-9)
                bleu_scores[i - 1, :] *= math.exp(1 - 1 / ratio)

        return bleu_scores, correct, pred_counts, ref_counts

    def compute_sentence_total_bleu(self, reference, translation, max_order=4):
        # compute sentence-level bleu score
        # total_result = torch.zeros_like(translation)
        reference_array = numpy.array(reference)
        translation_array = numpy.array(translation)
        # remove <s> token
        # reference_filt = [token for token in reference_array if token != 2 and token != 0 and token != 1]
        # translation_filt = [token for token in translation_array if token != 2 and token != 0 and token != 1]
        # since "bpe" split makes the training data contains no <unk>, "remove" has no big impact
        reference_filt = [token for token in reference_array if token not in [0, 1, 2]]
        translation_filt = [token for token in translation_array if token not in [0, 1, 2]]

        bleu_scores, _, _, _ = self._bleu(reference_filt, translation_filt, max_order)
        reward = bleu_scores[:, max_order - 1].copy()
        total_result = reward[-1]
        return total_result  # results are total, scalar

    def compute_sentence_bleu(self, reference, translation, max_order=4):
        delta_results = numpy.zeros_like(translation).astype('float32')  # [batch, times]
        reference_array = numpy.array(reference)
        translation_array = numpy.array(translation)
        # reference = _save_until_pad(reference)  # remove <pad> for reference
        reference_filt = [token for token in reference_array if token not in [0, 1, 2]]
        translation_filt = [token for token in translation_array if token not in [0, 1, 2]]

        bleu_scores, _, _, _ = self._bleu(reference_filt, translation_filt, max_order)
        # print(bleu_scores)
        reward = bleu_scores[:, max_order - 1]
        # print(reward)
        # delta rewards
        reward[1:] = reward[1:] - reward[:-1]
        pos = -1
        for i in range(len(translation)):
            if translation[i] not in [0, 1, 2]:
                pos = pos + 1
                delta_results[i] = reward[pos]
            else:
                delta_results[i] = 0.
        # print(results[index])  # debug
        delta_results = delta_results[::-1].cumsum(axis=0)[::-1]  # only one sentence
        delta_results = torch.from_numpy(delta_results.copy())
        return delta_results  # vector, results are delta rewards (one sentence)

    @staticmethod
    def reduce_metrics(logging_outputs) -> None:
        """Aggregate logging outputs from data parallel training."""
        loss_sum = sum(log.get('loss', 0) for log in logging_outputs)
        ntokens = sum(log.get('ntokens', 0) for log in logging_outputs)
        sample_size = sum(log.get('sample_size', 0) for log in logging_outputs)
        metrics.log_scalar(
            "loss", loss_sum / sample_size / math.log(2), sample_size, round=3
        )
        if sample_size != ntokens:
            metrics.log_scalar(
                "nll_loss", loss_sum / ntokens / math.log(2), ntokens, round=3
            )
            metrics.log_derived(
                "ppl", lambda meters: utils.get_perplexity(meters["nll_loss"].avg)
            )
        else:
            metrics.log_derived(
                "ppl", lambda meters: utils.get_perplexity(meters["loss"].avg)
            )
