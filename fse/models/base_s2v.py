#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Author: Oliver Borchers <borchers@bwl.uni-mannheim.de>
# Copyright (C) 2019 Oliver Borchers

from fse.models.sentencevectors import SentenceVectors
from fse.models.inputs import IndexedSentence

from gensim.models.base_any2vec import BaseWordEmbeddingsModel
from gensim.models.keyedvectors import BaseKeyedVectors, FastTextKeyedVectors
from gensim.utils import SaveLoad

from numpy import ndarray, memmap as np_memmap, float32 as REAL, empty, zeros, vstack, dtype

from wordfreq import available_languages, get_frequency_dict

from typing import List, Dict
from types import GeneratorType

from time import time
from psutil import virtual_memory

import logging
import warnings

logger = logging.getLogger(__name__)

class BaseSentence2VecModel(SaveLoad):
    """Base class containing common methods for training, using & evaluating sentence embeddings.

    Attributes
    ----------
    wv : :class:`~gensim.models.keyedvectors.BaseKeyedVectors`
        This object essentially contains the mapping between words and embeddings. After training, it can be used
        directly to query those embeddings in various ways. See the module level docstring for examples.
    
    sv : :class:`~fse.models.sentencevectors.SentenceVectors`
        This object contains the sentence vectors inferred from the training data. There will be one such vector
        for each unique docusentence supplied during training. They may be individually accessed using the index.

    See Also
    --------
    :class:`~fse.models.average.Average`.
        Average sentence Model.
    """

    def __init__(self, model:BaseKeyedVectors, mapfile_path:str=None, workers:int=2, lang_freq:str=None, fast_version:int=0, **kwargs):
        """
        Parameters
        ----------
        model : :class:`~gensim.models.keyedvectors.BaseKeyedVectors` or :class:`~gensim.models.base_any2vec.BaseWordEmbeddingsModel`
            This object essentially contains the mapping between words and embeddings. To compute the sentence embeddings
            the wv.vocab and wv.vector elements are required.
        mapfile_path : str, optional
            Optional path to store the vectors in for very large datasets
        workers : int, optional
            Number of working threads, used for multithreading.
        language : str, optional
            Some pre-trained embeddings, i.e. "GoogleNews-vectors-negative300.bin", do not contain information about
            the frequency of a word. As the frequency is required for estimating the word weights, we induce
            frequencies into the wv.vocab.count based on :class:`~wordfreq`
            If no frequency information is available, you can choose the language to estimate the frequency.
            See https://github.com/LuminosoInsight/wordfreq
        fast_version : {-1, 1}, optional
            Whether or not the fast cython implementation of the internal training methods is available. 1 means it is.
        **kwargs : object
            Key word arguments needed to allow children classes to accept more arguments.
        """

        # [ ] Implement Average Emebddings (Prototype)
        # [ ] :class: BaseSentence2VecModel
            # [ ] Check all dtypes before training
            # [ ] Check inf/nan
            # [ ] memmap for word vectors

        # [ ] Multi Core Implementation (Splitted Sentence Queue?)
            # [ ] Does asynchronous execution comply with lists? --> Accept only indexed sentences
            # [ ] How to deal with indexed sentences?
            # [ ] Automate CPU Selection with psutil
            # [ ] Count the effective words
        # [ ] Implement SIF Emebddings
            # [ ] If principal compnents exist, use them for the next train phase --> train + infer
            # [ ] pre_train_calls & post_train_calls

        # [ ] Implement uSIF Emebddings
            # [ ] Where to pass average sentence length?
        # [ ] Implement Fasttext Support
            # [ ] Estimate Memory does note account for fasttext ngram vectors
        
        # [ ] :class: SentenceVectors
            # [ ] Similarity for unseen documents --> Model.infer vector
            # [ ] For outputs, provide an indexable function to map indices to sentences
            # [ ] Does sv.vectors & wv.vectors collide during saving without mapfile path?
            # [ ] Decide which attributes to ignore when saving
        
        # [ ] :class: inputs
            # [ ] Tests for IndexedSentence
            # [ ] rewrite TaggedLineDocument
            # [ ] Document Boundary (DocId, Up, Low)

        # [X] Only int indices for sentences
        # [X] Aceppt lists as input
        # [X] Write base Sentence Embedding Class
        # [X] Indexed Sentence Class (Index, Sentence)
        # [X] Make a warning when sentences are not passed as [[str, str]] --> validate input
        # [X] How to best determine length?
        # [X] Initialization with zeros, but on first scan of sentences
        # [X] Unittest for inputs_check
        # [X] What happens, if the Indices in IndexedSentence are larger than the matrix?
        
        self.workers = int(workers)
        self.wv = None                              # TODO: Check if to ignore wv file when saving
                                                    # TODO: Check what happens to the induced frequency if you ignore wv during saving
        self.subword_information = False            # TODO: Implement Fasttext support

        if fast_version < 0:
            warnings.warn(
                "C extension not loaded, training/inferring will be slow. "
                "Install a C compiler and reinstall fse."
            )

        self._check_and_include_model(model)

        if lang_freq is not None:
            self._check_language_settings(lang_freq)
            self._induce_frequencies()

        self.sv = SentenceVectors(vector_size=self.wv.vector_size, mapfile_path=mapfile_path)
        self.prep = BaseSentence2VecPreparer()

    def _check_and_include_model(self, model:BaseKeyedVectors):
        """Check if the supplied model is a compatible model. """
        if isinstance(model, BaseWordEmbeddingsModel):
            self.wv = model.wv
        elif isinstance(model, BaseKeyedVectors):
            self.wv = model
        else:
            raise RuntimeError(f"Model must be child of BaseWordEmbeddingsModel or BaseKeyedVectors. Received {str(model)}")
        
        if isinstance(self.wv, FastTextKeyedVectors):
            # TODO: Remove after implementation
            raise NotImplementedError()

        if not hasattr(self.wv, 'vectors'):
            raise RuntimeError("Word vectors required for sentence embeddings not found.")
        if not hasattr(self.wv, 'vocab'):
            raise RuntimeError("Vocab required for sentence embeddings not found.")
    
    def _check_language_settings(self, lang_freq:str):
        """Check if the supplied language is a compatible with the wordfreq package"""
        if lang_freq in available_languages(wordlist='best'):
            self.lang_freq = str(lang_freq)
            logger.info("no frequency mode: using wordfreq for estimation"
                        f"of frequency for language: {self.lang_freq}")
        else:
            raise ValueError(f"Language {lang_freq} is not available in wordfreq")
    
    def _induce_frequencies(self, domain:int=2**31 - 1):
        """Induce frequencies for a pretrained model"""
        freq_dict = get_frequency_dict(self.lang_freq, wordlist='best')
        for word in self.wv.index2word:
            if word in freq_dict:
                self.wv.vocab[word].count = int(freq_dict[word] * domain)
            else:
                self.wv.vocab[word].count = int(1e-8 * domain)

    def _check_input_data_sanity(self, data_iterable=None):
        """Check if the input data complies with the required formats"""
        if data_iterable is None:
            raise TypeError("You must provide a data iterable to train on")
        elif isinstance(data_iterable, str):
            raise TypeError("Passed string. Input data must be iterable list of list of tokens or IndexedSentence")        
        elif isinstance(data_iterable, GeneratorType):
            raise TypeError("You can't pass a generator as the iterable. Try a sequence.")
        elif not hasattr(data_iterable, "__iter__"):
            raise TypeError("Iterable must provide __iter__ function")

    @classmethod
    def load(cls, *args, **kwargs):
        """Load a previously saved :class:`~fse.models.base_s2v.BaseSentence2VecModel`.

        Parameters
        ----------
        fname : str
            Path to the saved file.

        Returns
        -------
        :class:`~fse.models.base_s2v.BaseSentence2VecModel`
            Loaded model.

        """
        model = super(BaseSentence2VecModel, cls).load(*args, **kwargs)
        return model

    def save(self, *args, **kwargs):
        """Save the model.
        This saved model can be loaded again using :func:`~fse.models.base_s2v.BaseSentence2VecModel.load`

        Parameters
        ----------
        fname : str
            Path to the file.

        """
        # TODO: Make a decision what to store and what not
        # kwargs['ignore'] = kwargs.get('ignore', ['vectors_norm', 'cum_table'])
        super(BaseSentence2VecModel, self).save(*args, **kwargs)

    def scan_sentences(self, sentences:[List[List[str]], List[IndexedSentence]]=None, progress_per:int=5) -> [int, int, int, int]:
        logger.info("scanning all sentences and their word counts")

        current_time = time()
        total_sentences = 0
        total_words = 0
        average_length = 0
        empty_sentences = 0
        checked_string_types = 0            # Checks only once
        max_index = 0

        for obj_no, obj in enumerate(sentences):
            if isinstance(obj, IndexedSentence):
                index = obj.index
                sent = obj.words
            else:
                index = obj_no
                sent = obj

            if not checked_string_types:
                if not isinstance(sent, list) or not all(isinstance(w, str) for w in sent):
                    raise TypeError(f"Passed {type(sent)}: {sent}. Iterable must contain list of str.")
                checked_string_types += 1
            
            if time() - current_time > progress_per:
                current_time = time()
                logger.info(f"PROGRESS: finished {total_sentences} sentences with {total_words} words")

            max_index = max(max_index, index)
            total_sentences += 1
            total_words += len(sent)

            if not len(sent):
                empty_sentences += 1
        
        if empty_sentences:
            logger.warning(f"found {empty_sentences} empty sentences")

        if max_index >= total_sentences:
            raise RuntimeError(f"Maxium index {max_index} is larger than number of sentences {total_sentences}")

        average_length = int(total_words / total_sentences)

        logger.info(
            f"finished scanning {total_sentences} sentences with an average length of {average_length} and {total_words} total words"
        )
        return total_sentences, total_words, average_length, empty_sentences
    
    def estimate_memory(self, total_sentences:int, report:dict=None) -> Dict[str, int]:
        """Estimate the size of the sentence embedding

        Parameters
        ----------
        wv : :class:`~gensim.models.keyedvectors.BaseKeyedVectors`
            Contains all necessary information to compute size requirements
        total_sentences : int
            Number of sentences to be computed

        Returns
        -------
        dict
            Dictionary of esitmated sizes

        """
        if isinstance(self.wv, FastTextKeyedVectors):
            # TODO: Remove after implementation
            raise NotImplementedError()

        vocab_size = len(self.wv.vectors)

        report = report or {}
        report["Word Weights"] = vocab_size * dtype(REAL).itemsize
        report["Word Vectors"] = vocab_size * self.wv.vector_size * dtype(REAL).itemsize
        report["Sentence Vectors"] = total_sentences * self.wv.vector_size * dtype(REAL).itemsize
        report["Total"] = sum(report.values())
        mb_size = int(report["Total"] / 1024**2)
        logger.info(
            f"estimated memory for {total_sentences} sentences with "
            f"{self.wv.vector_size} dimensions and {vocab_size} vocabulary: "
            f"{mb_size} MB ({int(mb_size / 1024)} GB)"
        )
        if report["Total"] >= 0.95 * virtual_memory()[1]:
            warnings.warn("The embeddings will likely not fit into RAM. Consider to use mapfile_path")
        return report


    def train(self, sentences:[List[List[str]], List[IndexedSentence]]=None, update:bool=False, report_delay:int=5) -> [int,int]:

        self._check_input_data_sanity(sentences)
        total_sentences, total_words, average_length, empty_sentences = self.scan_sentences(sentences)
        self.estimate_memory(total_sentences)
        self.prep.prepare_vectors(sv=self.sv, total_sentences=total_sentences, update=update)
        #self._check_training_sanity()

        #self._pre_train_calls()

        #start_time = time()

        eff_sentences, eff_words = self._do_train_job(sentences)

        # Continue here with multi core implementation

        # trained_word_count_epoch, raw_word_count_epoch, job_tally_epoch = self._train_epoch(
        #             data_iterable, cur_epoch=cur_epoch, total_examples=total_examples,
        #             total_words=total_words, queue_factor=queue_factor, report_delay=report_delay)

        #self._post_train_calls()

        return total_sentences, total_words

    def infer(self, sentences:[List[List[str]], List[IndexedSentence]]=None) -> ndarray:
        raise NotImplementedError()

    def _pre_train_calls(self):
        raise NotImplementedError()

    def _post_train_calls(self):
        raise NotImplementedError()

    def _check_training_sanity(self):
        raise NotImplementedError()

    def _check_parameter_sanity(self):
        raise NotImplementedError()

    def _log_progress(self):
        raise NotImplementedError()

    def _log_train_end(self):
        raise NotImplementedError()
    
    def __str__(self):
        raise NotImplementedError()

    def _do_train_job(self, data_iterable) -> [int, int]:
        # TODO: Original implementation contains job_parameters and thread_paramters
        # return effective sentence count, effective word count
        raise NotImplementedError()

    def _check_dtypes(self):
        raise NotImplementedError()


class BaseSentence2VecPreparer(SaveLoad):
    """ Contains helper functions to perpare the weights for the training of BaseSentence2VecModel """

    def prepare_vectors(self, sv:SentenceVectors, total_sentences:int, update:bool=False):
        """Build tables and model weights based on final vocabulary settings."""
        if not update:
            self.reset_vectors(sv, total_sentences)
        else:
            self.update_vectors(sv, total_sentences)

    def reset_vectors(self, sv:SentenceVectors, total_sentences:int):
        """Initialize all sentence vectors to zero and overwrite existing files"""
        logger.info(f"initializing sentence vectors for {total_sentences} sentences")
        if sv.mapfile_path:
            sv.vectors = np_memmap(
                sv.mapfile_path + '.vectors', dtype=REAL,
                mode='w+', shape=(total_sentences, sv.vector_size))
        else:
            sv.vectors = empty((total_sentences, sv.vector_size), dtype=REAL)
        
        for i in range(total_sentences):
            sv.vectors[i] = zeros(sv.vector_size, dtype=REAL)
        sv.vectors_norm = None

    def update_vectors(self, sv:SentenceVectors, total_sentences:int):
        """Given existing sentence vectors, append new ones"""
        logger.info(f"appending sentence vectors for {total_sentences} sentences")
        sentences_before = len(sv.vectors)
        sentences_after = len(sv.vectors) + total_sentences

        if sv.mapfile_path:
            sv.vectors = np_memmap(
                sv.mapfile_path + '.vectors', dtype=REAL,
                mode='r+', shape=(sentences_after, sv.vector_size))
        else:
            newvectors = empty((total_sentences, sv.vector_size), dtype=REAL)
            for i in range(total_sentences):
                newvectors[i] = zeros(sv.vector_size, dtype=REAL)
            sv.vectors = vstack([sv.vectors, newvectors])
        sv.vectors_norm = None

        
        
