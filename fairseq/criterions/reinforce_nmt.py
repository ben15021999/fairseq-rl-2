# Copyright (c) Facebook, Inc. and its affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
#

from ctypes import util
import math
import torch
from fairseq import metrics
from dataclasses import dataclass, field
from fairseq.bert_score import BERTScorer, score

from collections import defaultdict
from fairseq import utils, search

from fairseq.criterions import FairseqCriterion, register_criterion
from torch.distributions import Categorical
from fairseq.scoring import bleu
# from fairseq.custom.evaluate_utils import batch_input_sequence_by_prefix_length
# from fairseq.custom.metrics import ngram_metrics
# from fairseq.custom.metrics import TrainingMetrics
# from fairseq.dataclass import FairseqDataclass


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


@register_criterion('reinforce_nmt')
class ReinforceNMT(FairseqCriterion):

    def __init__(self, task, max_len_decoding, max_order):
        super().__init__(task)

        self.max_len_decoding = max_len_decoding
        self.tgt_dict = task.tgt_dict
        self.max_order = max_order
        # self.bert_scorer = BERTScorer(self.bert_model)  # , device='cpu')
        self.scorer = bleu.Scorer(pad=self.tgt_dict.pad(), eos=self.tgt_dict.eos(), unk=self.tgt_dict.unk())
        # self.pad_token_id = self.bert_scorer._tokenizer.convert_tokens_to_ids('[PAD]')

        # File
        self.loss_stats_file = open('track_loss_prob_fbert_baseline.txt', 'w')
        self.loss_stats_file.write('loss\tprob\tfbert\n')

    @staticmethod
    def add_args(parser):
        """Add criterion-specific arguments to the parser."""
        # fmt: off
        parser.add_argument('--mle-weight', default='0.3', type=float, metavar='D',
                            help='MLE weight')

    def reword(self, reference_string, predicted_string):
        self.scorer.reset(one_init=True)
        # print("ref", reference_string)
        # print("pred", predicted_string)
        self.scorer.add(reference_string.type(torch.IntTensor), predicted_string.type(torch.IntTensor))
        return self.scorer.score(self.max_order)

    def array_to_sentence(self, array):
        sentence = []
        # print(self.tgt_dict.eos())
        for i in array:
            if i == self.tgt_dict.eos():
                break
            if i == self.tgt_dict.pad():
                continue
            s = self.tgt_dict[i]
            sentence.append(s)
        return sentence

    def forward(self, model, sample, reduce=True, generator=None):

        # Targets for reward computation
        target = sample['target']

        # Forward encoder
        encoder_out = model.encoder(
            sample['net_input']['src_tokens'], src_lengths=sample['net_input']['src_lengths'],
            # return_all_hiddens=True
        )

        # Decode translations sequentially (greedy decoding)
        pred_toks, lprob_toks = sequential_decoding(model, encoder_out,
                                                            max_len_decoding=self.max_len_decoding,
                                                            device='cuda')
        # model.train()
        # print(pred_toks)
        # print(lprob_toks)
        # predicted_output = [self.array_to_sentence(pred) for pred in pred_toks]
        # reference_output = [self.array_to_sentence(ref) for ref in target]

        # predicted_string = [' '.join(pred).replace('@@ ', '') for pred in predicted_output]
        # reference_string = [' '.join(ref).replace('@@ ', '') for ref in reference_output]
        # print(reference_string)
        # print(model.decoder.dictionary.__getitem__(self.pad_token_id))
        # Calculate entropy
        # probs = model.get_normalized_probs(net_output, log_probs=False)
        # # average_entropy = 0.
        # rows, cols = target.size()
        # cols_pred = pred_toks.size()[1]
        # cols_bas = bas_toks.size()[1]
        # refs_list = []
        # preds_list = []
        # bas_list = []
        # for i in range(rows):
        #     ref_sentence = []
        #     pred_sentence = []
        #     bas_sentence = []
        #     for j in range(cols):
        #         ref_word = model.decoder.dictionary.__getitem__(target[i, j].cpu().detach().numpy())
        #         # prob_entropy = Categorical(gsm_samples[i, j, :]).entropy().cpu().detach().numpy()
        #         if target[i, j] != self.pad_token_id:
        #             # average_entropy += prob_entropy
        #             ref_sentence.append(ref_word)
        #     for k in range(cols_pred):
        #         pred_word = model.decoder.dictionary.__getitem__(pred_toks[i, k].cpu().detach().numpy())
        #         if pred_toks[i, k] != self.pad_token_id:
        #             pred_sentence.append(pred_word)
        #     for l in range(cols_bas):
        #         bas_word = model.decoder.dictionary.__getitem__(bas_toks[i, l].cpu().detach().numpy())
        #         if bas_toks[i, l] != self.pad_token_id:
        #             bas_sentence.append(bas_word)
        #     refs_list.append(" ".join(ref_sentence))
        #     preds_list.append(" ".join(pred_sentence))
        #     bas_list.append(" ".join(bas_sentence))
        #     print('Tgt:  ', " ".join(ref_sentence))
        #     print('Pred:  ', " ".join(pred_sentence))
        #     print('Bas:  ', " ".join(bas_sentence))
        # average_entropy = average_entropy / (rows*cols)

        # Extract prob values
        # pred_toks_col = pred_toks.view(-1, 1).squeeze()
        # lprobs_col = lprobs.view(-1, lprobs.size()[-1])
        # lprobs_col = lprobs_col[torch.arange(lprobs_col.size()[0]), pred_toks_col]
        # lprobs_back = lprobs_col.view(pred_toks.size())
        # print(pred_toks.size())
        # print(lprob_toks[0, :])
        # print(lprob_toks[1, :])
        # lprobs_back = torch.gather(lprobs, dim=2, index=pred_toks)
        # print(lprobs_back.size())
        lprobs_added = lprob_toks.unsqueeze(0)
        lprobs_avg = lprobs_added.mean()
        # print(lprobs_added.size())
        # print(pred_toks.size())

        # Compute F-BERT
        # rewards_score = score(preds_list, refs_list, model_type='bert-base-uncased', device='cpu', verbose=False)
        # print(rewards_score)
        # print('F-BERT (og): ', rewards_score[2].mean())
        # rewards = self.bert_scorer.bert_loss_calculation(pred_toks, target, pad_token_id=self.pad_token_id,
        #                                                  both_tensors=True, out_type='f1_batch')
        # print(rewards)
        # BASELINE
        # rewards_baseline = self.bert_scorer.bert_loss_calculation(bas_toks, target, pad_token_id=self.pad_token_id,
        #                                                           both_tensors=True, out_type='f1_batch')
        # print(rewards_baseline)
        # Detach rewards from the loss function
        # rewards = torch.tensor([[self.reword(ref_i, pred_i) for ref_i, pred_i in zip(target, pred_toks)]])
        rewards = torch.tensor([[self.reword(ref_i, pred_i) for ref_i, pred_i in zip(target, pred_toks)]])
        # print(rewards)
        # rewards_baseline = torch.tensor([[self.reword(ref_i, base_i) for ref_i, base_i in zip(target, bas_toks)]])

        rewards_detached = rewards.detach()
        # rewards_baseline_detached = rewards_baseline.detach()
        # print(rewards)
        # print('F-BERT (model): ', rewards.mean())
        f_bert = rewards.sum()
        f_bert_mean = rewards.mean().data
        # print('prob_sum', lprobs_added.mean())

        # loss = - rewards_detached * lprobs_added
        # loss = (rewards_detached - torch.ones(rewards_detached.size()).to(self.bert_scorer.device)) * lprobs_added
        # loss = ((torch.ones(rewards_detached.size())*torch.tensor(0.7)).to(self.bert_scorer.device) -
        #         rewards_detached) * lprobs_added
        # print(lprobs_added)
        # print(rewards_detached)
        loss = -lprobs_added * utils.move_to_cuda(rewards_detached)
        loss = loss.sum()
        # print(loss)

        # Calculate accuracy
        # acc_target = target.view(-1, 1).squeeze()
        # pred = lprobs.contiguous().view(-1, lprobs.size(-1)).max(1)[1]
        # non_padding = acc_target.view(-1, 1).ne(model.decoder.dictionary.pad_index).squeeze()
        # total_num = non_padding.sum()
        # num_correct = pred.eq(acc_target) \
        #     .masked_select(non_padding) \
        #     .sum()

        sample_size = sample['ntokens']
        logging_output = {
            'loss': loss.data,
            # 'ntokens': sample['ntokens'],
            'n_sentences': sample['target'].size(0),
            'sample_size': sample_size,
            'f_bert': f_bert.data
        }

        self.loss_stats_file.write(str(loss.detach().cpu().numpy()) + '\t' + str(lprobs_avg.detach().cpu().numpy()) + '\t' +
                                   str(f_bert_mean.detach().cpu().numpy()) + '\n')

        return loss, sample_size, logging_output

    @staticmethod
    def reduce_metrics(logging_outputs) -> None:
        """Aggregate logging outputs from data parallel training."""
        loss_sum = sum(log.get('loss', 0) for log in logging_outputs)
        f_bert_sum = sum(log.get('f_bert', 0) for log in logging_outputs)
        # print('Sum ', f_bert_sum)
        # ntokens = sum(log.get('ntokens', 0) for log in logging_outputs)
        n_sentences = sum(log.get('n_sentences', 0) for log in logging_outputs)
        # print('Avg ', f_bert_sum / n_sentences)
        # n_correct = sum(log.get('n_correct', 0) for log in logging_outputs)
        # total_n = sum(log.get('total_n', 0) for log in logging_outputs)

        metrics.log_scalar('loss', loss_sum / n_sentences, n_sentences, round=3)
        metrics.log_scalar('f_bert', f_bert_sum / n_sentences, n_sentences, round=3)
        # metrics.log_scalar('accuracy', float(n_correct) / float(total_n), total_n, round=3)
        # metrics.log_derived('ppl', lambda meters: utils.get_perplexity(meters['loss'].avg))


# Test
def _forward_one(model, encoded_source, tokens, incremental_states=None, temperature=1., return_attn=False,
                 return_logits=False, **decoder_kwargs):
    # print(return_logits)
    if incremental_states is not None:
        decoder_out = list(model.decoder(tokens, encoded_source, incremental_state=incremental_states))
    else:
        decoder_out = list(model.decoder(tokens, encoded_source, **decoder_kwargs))
    decoder_out[0] = decoder_out[0][:, -1:, :].clone()
    # print(decoder_out[0].size())
    if temperature != 1.:
        decoder_out[0].div_(temperature)
    attn = decoder_out[1]
    if type(attn) is dict:
        attn = attn['attn'][0]
    attn = None
    if attn is not None:
        if type(attn) is dict:
            attn = attn['attn']
        attn = attn[:, :, -1, :]  # B x L x t
    if return_logits:
        logits_t = decoder_out[0][:, -1, :].clone()
        return logits_t, attn
    log_probs = model.get_normalized_probs(decoder_out, log_probs=True)
    log_probs = log_probs[:, -1, :].clone()
    return log_probs, attn


def sequential_decoding(model, encoded_source, max_len_decoding, device):
    # model.eval()
    pred_toks_pred = []
    # pred_toks_bas = []
    batch_size = encoded_source[0].size()[1]
    eos_token_id = torch.tensor(model.decoder.dictionary.eos()).to(device)
    pad_token_id = torch.tensor(model.decoder.dictionary.pad()).to(device)
    context_pred = torch.tensor([model.decoder.dictionary.eos()] * batch_size).to(device).unsqueeze(1)
    # context_bas = torch.tensor([model.decoder.dictionary.eos()] * batch_size).to(device).unsqueeze(1)
    # print(context_pred)
    states = {}
    lprob_toks_pred = 0
    all_lprobs_pred = []
    masking_matrix_pred = []
    aux_masking_matrix_pred = []
    # lprob_toks_bas = []
    # all_lprobs_bas = []
    # masking_matrix_bas = []
    # aux_masking_matrix_bas = []
    finished = torch.tensor([0] * batch_size).to(device).unsqueeze(1)
    for tstep in range(max_len_decoding):
        # We need 2 sampling techniques
        # lprobs_pred, attn_t_pred = _forward_one(model, encoded_source, context_pred, incremental_states=states, return_logits=True)
        # logits, attn_t_pred = _forward_one(model, encoded_source, context_pred, incremental_states=states, return_logits=True)
        # lprobs_bas, attn_t_bas = _forward_one(model, encoded_source, context_bas, incremental_states=states)?
        # lprobs[:, pad_token_id] = -math.inf  # never select pad  (MAYBE I CAN ADD MIN LENGTH?)
        # print(lprobs.size())
        # Argmax
        # pred_tok_bas = lprobs_bas.argmax(dim=1, keepdim=True)
        # lprob_tok_bas = torch.gather(lprobs_bas, dim=1, index=pred_tok_bas)
        # Sampling
        logits, _ = model.decoder(context_pred, encoded_source, incremental_state=states)
        dist = Categorical(logits=logits)
        # pred_tok_pred = dist.sample().unsqueeze(dim=1)
        next_word = dist.sample()
        print(next_word)
        # lprob_tok_pred = torch.gather(lprobs_pred, dim=1, index=pred_tok_pred)
        lprob_tok_pred = dist.log_prob(next_word)
        # print(lprob_tok_pred)
        # next_word = next_word.unsqueeze(dim=1)
        # print(lprob_tok.size())
        # print(lprob_tok_index.size())
        # Check if predicted token is <eos>

        pred_toks_pred.append(next_word)
        context_pred = torch.cat((context_pred, next_word), 1)
        lprob_toks_pred += lprob_tok_pred

        is_eos = torch.eq(next_word, eos_token_id)
        finished += is_eos
        # print(finished)
        if (finished >= 1).sum() == batch_size:
            break

        # pred_token_bool = torch.where(next_word == eos_token_id, torch.tensor(1.0).to(device),
        #                               torch.tensor(0.0).to(device))
        # bas_token_bool = torch.where(pred_tok_bas == eos_token_id, torch.tensor(1.0).to(device),
        #                               torch.tensor(0.0).to(device))
        # if len(aux_masking_matrix_pred) > 0:
        #     pred_token_bool = torch.logical_or(aux_masking_matrix_pred[-1], pred_token_bool)
        #     pred_token_bool = torch.where(pred_token_bool == True, torch.tensor(1.0).to(device),
        #                                   torch.tensor(0.0).to(device))
        #     see_if_previous_was_eos = torch.logical_or(masking_matrix_pred[-1], aux_masking_matrix_pred[-1]).to(device)
        #     pred_token_bool_true = torch.logical_and(see_if_previous_was_eos, pred_token_bool).to(device)
        #     masking_matrix_pred.append(pred_token_bool_true)
            # BASELINE
            # bas_token_bool = torch.logical_or(aux_masking_matrix_bas[-1], bas_token_bool)
            # bas_token_bool = torch.where(bas_token_bool == True, torch.tensor(1.0).to(device),
            #                               torch.tensor(0.0).to(device))
            # see_if_previous_was_eos_bas = torch.logical_or(masking_matrix_bas[-1],
            #                                                aux_masking_matrix_bas[-1]).to(device)
            # bas_token_bool_true = torch.logical_and(see_if_previous_was_eos_bas, bas_token_bool).to(device)
            # masking_matrix_bas.append(bas_token_bool_true)
        # else:
            # masking_matrix_pred.append(torch.zeros(pred_token_bool.size()).to(device))
            # masking_matrix_bas.append(torch.zeros(bas_token_bool.size()).to(device))
        # aux_masking_matrix_pred.append(pred_token_bool)
        # aux_masking_matrix_bas.append(bas_token_bool)

        # all_lprobs_pred.append(lprobs_pred)
        # lprob_toks_bas.append(lprob_tok_bas)
        # all_lprobs_bas.append(lprobs_bas)
        # count_token_pred = pred_token_bool[pred_token_bool == 0].size()[0]
        # count_token_bas = bas_token_bool[bas_token_bool == 0].size()[0]
        # count_token = count_token_pred + count_token_bas
        # count_token = count_token_pred
        # if count_token == 0:
        #     break
    # print(lprob_toks_pred)
    # for tok in pred_toks:
    #     print(model.decoder.dictionary.__getitem__(tok[0]))
    # masking_matrix_pred = torch.cat(masking_matrix_pred, 1)
    pred_toks_pred = torch.cat(pred_toks_pred, 1)
    # lprob_toks_pred = torch.cat(lprob_toks_pred, 0)
    # all_lprobs_pred = torch.stack(all_lprobs_pred, 1)
    # BASELINE
    # masking_matrix_bas = torch.cat(masking_matrix_bas, 1)
    # pred_toks_bas = torch.cat(pred_toks_bas, 1)
    print(context_pred)
    # Apply masking (padding tokens after the <eos> token.)
    pred_toks_pred[masking_matrix_pred == 1.0] = pad_token_id
    # pred_toks_bas[masking_matrix_bas == 1.0] = pad_token_id
    # print(pred_toks[0,:])
    # Apply masking (set probability values to zero)
    # all_lprobs_pred[masking_matrix_pred == 1.0] = torch.zeros(all_lprobs_pred.size()[-1]).to(device)

    return pred_toks_pred, lprob_toks_pred