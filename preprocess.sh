TEXT=data/en-vi_IWSLT2015
fairseq-preprocess --source-lang en --target-lang vi \
    --trainpref $TEXT/train/train.bpe --validpref $TEXT/valid/valid.bpe --testpref $TEXT/test/test.bpe \
    --destdir data-bin/data.tokenized.en-vi.v1 \
    --bos [unused0] \
    --pad [PAD] \
    --eos [unused1] \
    --unk [UNK] \
    --tgtdict_add_sentence_limit_words_after


